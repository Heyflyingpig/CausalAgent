"""searxng init 脚本单元测试：兜底生成 settings.yml 并注入随机 secret_key。

脚本为纯 POSIX sh，通过 subprocess 直接执行真实脚本，在临时目录中验证：
- 缺失时复制 example 并注入 64 位 hex secret_key
- 已存在时幂等跳过，绝不覆盖用户配置
- example 缺失时报错退出
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "searxng" / "init" / "init_settings.sh"

EXAMPLE = """use_default_settings:
  engines:
    keep_only:
      - arxiv
      - crossref
      - openalex

server:
  secret_key: "ultrasecretkey"
  limiter: false
  image_proxy: true

search:
  formats:
    - html
    - json

redis:
  url: redis://valkey:6379/0

engines:
  - name: arxiv
    disabled: false
  - name: crossref
    disabled: false
    timeout: 15
  - name: openalex
    disabled: false
"""

SECRET_RE = re.compile(r'secret_key: "([0-9a-f]{64})"')


def _run_init(
    config_dir: Path,
    *,
    path_prefix: Path | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SEARXNG_CONFIG_DIR"] = str(config_dir)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["sh", str(SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
    )


def test_generates_settings_yml_with_random_secret_when_missing(tmp_path):
    (tmp_path / "settings.yml.example").write_text(EXAMPLE, encoding="utf-8")
    proc = _run_init(tmp_path)
    assert proc.returncode == 0, proc.stderr

    target = tmp_path / "settings.yml"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "ultrasecretkey" not in content
    match = SECRET_RE.search(content)
    assert match, "secret_key 应为 64 位 hex，实际内容:\n" + content


def test_generates_settings_yml_preserves_structure(tmp_path):
    (tmp_path / "settings.yml.example").write_text(EXAMPLE, encoding="utf-8")
    proc = _run_init(tmp_path)
    assert proc.returncode == 0, proc.stderr

    content = (tmp_path / "settings.yml").read_text(encoding="utf-8")
    # 仅 secret_key 变化，其余结构（引擎白名单、json 格式、redis）原样保留。
    assert "keep_only" in content
    assert "- json" in content
    assert "redis://valkey:6379/0" in content
    assert content.count("ultrasecretkey") == 0
    assert not list(tmp_path.glob(".settings.yml.tmp.*"))


def test_idempotent_skips_existing_settings_yml(tmp_path):
    (tmp_path / "settings.yml.example").write_text(EXAMPLE, encoding="utf-8")
    custom = 'server:\n  secret_key: "user-custom-value"\n  limiter: true\n'
    (tmp_path / "settings.yml").write_text(custom, encoding="utf-8")

    proc = _run_init(tmp_path)
    assert proc.returncode == 0, proc.stderr

    # 已存在的内容原样保留，不被 example 覆盖。
    assert (tmp_path / "settings.yml").read_text(encoding="utf-8") == custom


def test_fails_when_example_missing(tmp_path):
    proc = _run_init(tmp_path)
    assert proc.returncode != 0
    assert not (tmp_path / "settings.yml").exists()


def test_generation_failure_does_not_publish_partial_settings(tmp_path):
    """生成 secret 失败时，目标文件不能先于完整校验出现。"""
    (tmp_path / "settings.yml.example").write_text(EXAMPLE, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python3"
    fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_python.chmod(0o755)

    proc = _run_init(tmp_path, path_prefix=bin_dir)

    assert proc.returncode != 0
    assert not (tmp_path / "settings.yml").exists()
    assert not list(tmp_path.glob(".settings.yml.tmp.*"))
