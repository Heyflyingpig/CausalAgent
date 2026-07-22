from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import venv
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_VERSIONS = ["0.4.3", "0.4.0", "0.3.7", "0.2.15", "0.1.21"]
PROJECT_STACK = [
    "langchain==1.3.1",
    "langchain-core==1.4.0",
    "langchain-openai==1.2.2",
    "langchain-community==0.4.2",
    "langchain-text-splitters==1.1.2",
]
MARKER = "@@RAGAS_IMPORT_PROBE@@"


def parse_args() -> argparse.Namespace:
    """Parse command line options for the Ragas import probe."""
    parser = argparse.ArgumentParser(
        description=(
            "Probe candidate Ragas versions in isolated virtual environments "
            "without changing the current conda or Docker environment."
        )
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        default=DEFAULT_VERSIONS,
        help="Candidate Ragas versions to test.",
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Only probe the currently active Python environment.",
    )
    parser.add_argument(
        "--keep-envs",
        action="store_true",
        help="Keep generated virtual environments under --work-dir for inspection.",
    )
    parser.add_argument(
        "--work-dir",
        default="tmp/ragas_import_probe",
        help="Directory used when --keep-envs is enabled.",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="Optional path to write the full JSON result.",
    )
    return parser.parse_args()


def venv_python_path(venv_dir: Path) -> Path:
    """Return the Python executable path for a virtual environment."""
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run_command(command: List[str], timeout: int = 600) -> Dict[str, Any]:
    """Run a subprocess and capture output for reporting."""
    started_at = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return {
        "returncode": completed.returncode,
        "seconds": round(time.perf_counter() - started_at, 3),
        "stdout": completed.stdout[-5000:],
        "stderr": completed.stderr[-5000:],
    }


def build_probe_code(with_vertexai_shim: bool) -> str:
    """Build the Python code executed inside each probed environment."""
    shim = ""
    if with_vertexai_shim:
        shim = r"""
import importlib.util
import sys
import types

module_name = "langchain_community.chat_models.vertexai"
if module_name not in sys.modules and importlib.util.find_spec(module_name) is None:
    try:
        from langchain_community.llms.vertexai import VertexAI
        module = types.ModuleType(module_name)
        module.__package__ = "langchain_community.chat_models"
        module.ChatVertexAI = VertexAI
        sys.modules[module_name] = module
    except Exception as exc:
        SHIM_ERROR = repr(exc)
"""

    return (
        shim
        + r'''
import importlib.metadata
import inspect
import json
import sys
import warnings


def run_test(name, source):
    """Execute one import test and return a compact result."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        namespace = {"inspect": inspect}
        try:
            exec(source, namespace, namespace)
            return {
                "ok": True,
                "error": "",
                "warnings": [str(item.message) for item in caught],
                "details": namespace.get("DETAILS", {}),
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": repr(exc),
                "warnings": [str(item.message) for item in caught],
                "details": namespace.get("DETAILS", {}),
            }


tests = {
    "core_public": """
import ragas
from ragas import EvaluationDataset, evaluate
from ragas.run_config import RunConfig
DETAILS = {"ragas_version": getattr(ragas, "__version__", "unknown")}
""",
    "wrappers_public": """
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
DETAILS = {
    "llm_wrapper": LangchainLLMWrapper.__name__,
    "embeddings_wrapper": LangchainEmbeddingsWrapper.__name__,
}
""",
    "metrics_public_deprecated": """
from ragas.metrics import answer_relevancy, context_recall, context_utilization, faithfulness
DETAILS = {
    "metrics": [
        getattr(faithfulness, "name", "faithfulness"),
        getattr(answer_relevancy, "name", "answer_relevancy"),
        getattr(context_utilization, "name", "context_utilization"),
        getattr(context_recall, "name", "context_recall"),
    ]
}
""",
    "metrics_collections_public": """
from ragas.metrics.collections import AnswerRelevancy, ContextRecall, ContextUtilization, Faithfulness
DETAILS = {
    "constructors": {
        "Faithfulness": str(inspect.signature(Faithfulness)),
        "AnswerRelevancy": str(inspect.signature(AnswerRelevancy)),
        "ContextUtilization": str(inspect.signature(ContextUtilization)),
        "ContextRecall": str(inspect.signature(ContextRecall)),
    }
}
""",
    "metrics_current_internal": """
from ragas.metrics._answer_relevance import answer_relevancy
from ragas.metrics._context_precision import context_utilization
from ragas.metrics._context_recall import context_recall
from ragas.metrics._faithfulness import faithfulness
DETAILS = {
    "metrics": [
        getattr(faithfulness, "name", "faithfulness"),
        getattr(answer_relevancy, "name", "answer_relevancy"),
        getattr(context_utilization, "name", "context_utilization"),
        getattr(context_recall, "name", "context_recall"),
    ]
}
""",
}

result = {
    "python": sys.executable if "sys" in globals() else "",
    "shim_error": globals().get("SHIM_ERROR", ""),
    "packages": {},
    "tests": {},
}
for package_name in [
    "ragas",
    "langchain",
    "langchain-core",
    "langchain-openai",
    "langchain-community",
]:
    try:
        result["packages"][package_name] = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        result["packages"][package_name] = ""

for test_name, source in tests.items():
    result["tests"][test_name] = run_test(test_name, source)

print("'''
        + MARKER
        + '''" + json.dumps(result, ensure_ascii=False, sort_keys=True))
'''
    )


def run_import_probe(python_exe: Path, with_vertexai_shim: bool) -> Dict[str, Any]:
    """Run import checks in a Python interpreter and parse the JSON marker."""
    completed = run_command(
        [str(python_exe), "-c", build_probe_code(with_vertexai_shim)],
        timeout=120,
    )
    parsed: Dict[str, Any] = {}
    for line in completed["stdout"].splitlines():
        if line.startswith(MARKER):
            parsed = json.loads(line[len(MARKER) :])
            break
    return {
        "mode": "with_vertexai_shim" if with_vertexai_shim else "plain",
        "command": [str(python_exe), "-c", "<probe_code>"],
        "process": completed,
        "parsed": parsed,
    }


def create_probe_environment(version: str, keep_envs: bool, work_dir: Path) -> Dict[str, Any]:
    """Create a temporary venv, install one Ragas candidate, and run probes."""
    if keep_envs:
        safe_version = version.replace(".", "_").replace("-", "_")
        venv_dir = work_dir / f"ragas_{safe_version}_{int(time.time())}"
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix=f"ragas-{version}-")
        venv_dir = Path(temp_dir.name)
        cleanup = temp_dir

    result: Dict[str, Any] = {
        "version": version,
        "venv_dir": str(venv_dir),
        "install": {},
        "probes": [],
    }
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
        python_exe = venv_python_path(venv_dir)
        install_command = [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            f"ragas=={version}",
            *PROJECT_STACK,
        ]
        result["install"] = run_command(install_command, timeout=900)
        if result["install"]["returncode"] == 0:
            result["probes"].append(run_import_probe(python_exe, with_vertexai_shim=False))
            result["probes"].append(run_import_probe(python_exe, with_vertexai_shim=True))
    finally:
        if cleanup:
            cleanup.cleanup()
    return result


def probe_current_environment() -> Dict[str, Any]:
    """Run import probes against the currently active Python environment."""
    python_exe = Path(sys.executable)
    return {
        "version": "current",
        "venv_dir": "",
        "install": {"returncode": 0, "seconds": 0, "stdout": "", "stderr": ""},
        "probes": [
            run_import_probe(python_exe, with_vertexai_shim=False),
            run_import_probe(python_exe, with_vertexai_shim=True),
        ],
    }


def summarize_probe(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact pass/fail summary for one candidate result."""
    summary: Dict[str, Any] = {
        "version": entry["version"],
        "install_ok": entry.get("install", {}).get("returncode") == 0,
        "plain": {},
        "with_vertexai_shim": {},
    }
    for probe in entry.get("probes", []):
        parsed = probe.get("parsed") or {}
        tests = parsed.get("tests", {})
        summary[probe["mode"]] = {
            key: value.get("ok", False)
            for key, value in tests.items()
        }
        summary[probe["mode"]]["packages"] = parsed.get("packages", {})
    return summary


def print_summary(entries: List[Dict[str, Any]]) -> None:
    """Print a compact table for human review."""
    print("\nRagas import probe summary")
    print("version | install | mode | core | wrappers | metrics(deprecated) | collections | current_internal")
    print("-" * 100)
    for entry in entries:
        compact = summarize_probe(entry)
        if not compact["install_ok"]:
            print(f"{entry['version']} | fail | - | - | - | - | - | -")
            continue
        for mode in ["plain", "with_vertexai_shim"]:
            values = compact.get(mode, {})
            print(
                " | ".join(
                    [
                        entry["version"],
                        "ok",
                        mode,
                        "ok" if values.get("core_public") else "fail",
                        "ok" if values.get("wrappers_public") else "fail",
                        "ok" if values.get("metrics_public_deprecated") else "fail",
                        "ok" if values.get("metrics_collections_public") else "fail",
                        "ok" if values.get("metrics_current_internal") else "fail",
                    ]
                )
            )


def main() -> int:
    """Run Ragas version probes and optionally persist the JSON result."""
    args = parse_args()
    if args.current_only:
        results = [probe_current_environment()]
    else:
        work_dir = Path(args.work_dir)
        if work_dir.exists() and not work_dir.is_dir():
            raise NotADirectoryError(work_dir)
        results = [
            create_probe_environment(version, keep_envs=args.keep_envs, work_dir=work_dir)
            for version in args.versions
        ]

    output = {"results": results, "summary": [summarize_probe(item) for item in results]}
    print_summary(results)
    print("\nFull JSON:")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote JSON result to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
