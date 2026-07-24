import dataclasses
import logging
import math
import sys
import types
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch

from Agent.knowledge_base.rag_runtime import (
    RagRuntimeConfig,
    RagRuntimeInitializationError,
    create_rag_runtime,
)
from Agent.knowledge_base.sparse_retriever import (
    InMemoryBm25Retriever,
    _SparseEntry,
    bm25_score,
    tokenize_text,
)


def _runtime_config(**embedding_overrides):
    """创建不含真实资源路径的 Runtime 单测配置。"""
    embedding_config = {
        "status": "ready",
        "mode": "local",
        "provider": "huggingface",
        "model": "unit-model",
        "path": "unit-model-path",
    }
    embedding_config.update(embedding_overrides)
    return RagRuntimeConfig(
        vector_db_dir="unit-db",
        collection_name="unit-collection",
        production_config_path="unit-config.json",
        embedding_config=embedding_config,
    )


class RagRuntimeLifecycleTests(unittest.TestCase):
    def test_config_is_frozen_and_strips_secret_values(self):
        config = _runtime_config(api_key="must-not-survive")

        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.collection_name = "other"
        with self.assertRaises(TypeError):
            config.embedding_config["model"] = "other"
        self.assertNotIn("api_key", config.embedding_config)

    def test_runtime_initializes_resources_once_in_fixed_order(self):
        order = []
        embedding = object()
        vector_db = SimpleNamespace()
        sparse = object()

        with patch(
            "Agent.knowledge_base.rag_runtime._validate_vector_db_directory",
            side_effect=lambda _config: order.append("directory"),
        ) as validate_directory, patch(
            "Agent.knowledge_base.rag_runtime._validate_embedding_config",
            side_effect=lambda _config: order.append("embedding_config"),
        ) as validate_embedding, patch(
            "Agent.knowledge_base.rag_runtime._create_embedding_function",
            side_effect=lambda _config: order.append("embedding") or embedding,
        ) as create_embedding, patch(
            "Agent.knowledge_base.rag_runtime._open_existing_vector_db",
            side_effect=lambda _config, _embedding: order.append("chroma") or vector_db,
        ) as open_vector_db, patch(
            "Agent.knowledge_base.rag_runtime._count_chunks",
            side_effect=lambda _db: order.append("count") or 3,
        ) as count_chunks, patch(
            "Agent.knowledge_base.rag_runtime.InMemoryBm25Retriever.from_vector_db",
            side_effect=lambda _db: order.append("sparse") or sparse,
        ) as build_sparse:
            runtime = create_rag_runtime(_runtime_config(), answer_llm="llm")

        self.assertEqual(
            order,
            ["directory", "embedding_config", "embedding", "chroma", "count", "sparse"],
        )
        self.assertIs(runtime.embedding, embedding)
        self.assertIs(runtime.vector_db, vector_db)
        self.assertIs(runtime.sparse_retriever, sparse)
        for mocked in (
            validate_directory,
            validate_embedding,
            create_embedding,
            open_vector_db,
            count_chunks,
            build_sparse,
        ):
            mocked.assert_called_once()

    def test_failure_reports_stage_and_returns_no_partial_runtime(self):
        with patch(
            "Agent.knowledge_base.rag_runtime._validate_vector_db_directory"
        ), patch(
            "Agent.knowledge_base.rag_runtime._validate_embedding_config",
            side_effect=ValueError("invalid"),
        ), patch(
            "Agent.knowledge_base.rag_runtime._create_embedding_function"
        ) as create_embedding:
            with self.assertRaises(RagRuntimeInitializationError) as raised:
                create_rag_runtime(_runtime_config(), answer_llm="llm")

        self.assertEqual(raised.exception.stage, "embedding_config")
        create_embedding.assert_not_called()

    def test_missing_collection_and_empty_collection_fail_strictly(self):
        common_patches = (
            patch("Agent.knowledge_base.rag_runtime._validate_vector_db_directory"),
            patch("Agent.knowledge_base.rag_runtime._validate_embedding_config"),
            patch("Agent.knowledge_base.rag_runtime._create_embedding_function", return_value=object()),
        )
        with common_patches[0], common_patches[1], common_patches[2], patch(
            "Agent.knowledge_base.rag_runtime._open_existing_vector_db",
            side_effect=RuntimeError("collection missing"),
        ):
            with self.assertRaises(RagRuntimeInitializationError) as missing:
                create_rag_runtime(_runtime_config(), answer_llm="llm")
        self.assertEqual(missing.exception.stage, "chroma_collection")

        vector_db = object()
        with patch("Agent.knowledge_base.rag_runtime._validate_vector_db_directory"), patch(
            "Agent.knowledge_base.rag_runtime._validate_embedding_config"
        ), patch(
            "Agent.knowledge_base.rag_runtime._create_embedding_function", return_value=object()
        ), patch(
            "Agent.knowledge_base.rag_runtime._open_existing_vector_db", return_value=vector_db
        ), patch(
            "Agent.knowledge_base.rag_runtime._count_chunks", side_effect=ValueError("empty")
        ):
            with self.assertRaises(RagRuntimeInitializationError) as empty:
                create_rag_runtime(_runtime_config(), answer_llm="llm")
        self.assertEqual(empty.exception.stage, "chunk_count")

    def test_startup_log_does_not_include_secret(self):
        secret = "unit-secret-value"
        config = _runtime_config(api_key=secret)
        with patch("Agent.knowledge_base.rag_runtime._validate_vector_db_directory"), patch(
            "Agent.knowledge_base.rag_runtime._validate_embedding_config"
        ), patch(
            "Agent.knowledge_base.rag_runtime._create_embedding_function", return_value=object()
        ), patch(
            "Agent.knowledge_base.rag_runtime._open_existing_vector_db", return_value=object()
        ), patch(
            "Agent.knowledge_base.rag_runtime._count_chunks", return_value=1
        ), patch(
            "Agent.knowledge_base.rag_runtime.InMemoryBm25Retriever.from_vector_db",
            return_value=object(),
        ), self.assertLogs(level=logging.INFO) as captured:
            create_rag_runtime(config, answer_llm="llm")

        self.assertNotIn(secret, "\n".join(captured.output))


class SparseRetrieverParityTests(unittest.TestCase):
    def _retriever(self):
        """构造固定语料的只读检索器。"""
        texts = ["因果 推断 treatment_effect", "相关性不是因果", "unrelated"]
        entries = []
        doc_freq = Counter()
        total_length = 0
        for index, text in enumerate(texts):
            tokens = tokenize_text(text)
            term_freq = Counter(tokens)
            doc_freq.update(term_freq.keys())
            total_length += len(tokens)
            entries.append(
                _SparseEntry(
                    page_content=text,
                    metadata={"chunk_id": f"c{index}"},
                    term_freq=MappingProxyType(dict(term_freq)),
                    length=max(len(tokens), 1),
                )
            )
        return InMemoryBm25Retriever(
            entries=tuple(entries),
            doc_freq=MappingProxyType(dict(doc_freq)),
            avg_length=total_length / len(entries),
        )

    def test_tokenizer_truncation_and_bm25_formula_match_legacy(self):
        self.assertEqual(tokenize_text("因果_test"), ["因", "果", "因果", "test"])
        self.assertEqual(len(tokenize_text("因" * 600)), 512)

        query_tokens = ["a"]
        entry = {"term_freq": {"a": 2}, "length": 4}
        expected_idf = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))
        expected = expected_idf * (2 * 2.5 / (2 + 1.5 * (1 - 0.75 + 0.75 * 4 / 3)))
        self.assertAlmostEqual(bm25_score(query_tokens, entry, {"a": 1}, 3, 3), expected)

    def test_from_vector_db_reads_once_and_freezes_internal_corpus(self):
        fake_query_rag = types.ModuleType("Agent.knowledge_base.query_rag")
        fake_query_rag._normalize_chunk_metadata = (
            lambda metadata, _content, fallback_index=0: {
                **metadata,
                "chunk_id": metadata.get("chunk_id", f"c{fallback_index}"),
            }
        )
        vector_db = Mock()
        vector_db.get.return_value = {
            "documents": ["因果推断", "相关性"],
            "metadatas": [{"chunk_id": "c0"}, {"chunk_id": "c1"}],
            "ids": ["v0", "v1"],
        }

        with patch.dict(sys.modules, {"Agent.knowledge_base.query_rag": fake_query_rag}):
            retriever = InMemoryBm25Retriever.from_vector_db(vector_db)

        vector_db.get.assert_called_once_with(include=["documents", "metadatas"])
        self.assertEqual(retriever.size, 2)
        with self.assertRaises(TypeError):
            retriever.entries[0].metadata["changed"] = True
        result = retriever.search("因果", 1)
        result[0]["metadata"]["changed"] = True
        self.assertNotIn("changed", retriever.entries[0].metadata)

    def test_search_order_top_k_and_results_do_not_share_mutable_state(self):
        retriever = self._retriever()
        first = retriever.search("因果", top_k=2)
        second = retriever.search("因果", top_k=2)

        self.assertEqual([item["metadata"]["chunk_id"] for item in first], ["c0", "c1"])
        self.assertEqual(len(first), 2)
        first[0]["metadata"]["changed"] = True
        first[0]["retrieval_sources"].add("dense")
        self.assertNotIn("changed", second[0]["metadata"])
        self.assertEqual(second[0]["retrieval_sources"], {"sparse"})

    def test_concurrent_searches_return_independent_candidates(self):
        retriever = self._retriever()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: retriever.search("因果", 2), range(2)))

        self.assertIsNot(results[0], results[1])
        self.assertIsNot(results[0][0]["metadata"], results[1][0]["metadata"])
        self.assertIsNot(results[0][0]["retrieval_sources"], results[1][0]["retrieval_sources"])


if __name__ == "__main__":
    unittest.main()
