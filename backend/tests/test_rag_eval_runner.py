import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from app.core.config import settings
from app.services.llm_gateway import LLMGenerationResult
from evals import rag_evaluator, runner


class _DeterministicKeywordEmbedder:
    """
    Fast, deterministic bag-of-keywords embedder for unit tests (zero Torch/HF download).
    Maps each CS topic into orthogonal dimensions so real ChromaDB cosine retrieval
    ranks matching curriculum chunks accurately without internet or model weights.
    """

    KEYWORDS = [
        "merge sort",
        "binary search",
        "hash table",
        "translation lookaside buffer",
        "coffman",
        "process heap",
        "three-way handshake",
        "dns",
        "acid",
        "b-tree",
        "closure",
        "recursion",
    ]

    def encode(self, texts, show_progress_bar=False):
        class _VecArray:
            def __init__(self, rows):
                self._rows = rows

            def tolist(self):
                return self._rows

        rows = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if kw in low else 0.05 for kw in self.KEYWORDS]
            rows.append(vec)
        return _VecArray(rows)


# ==============================================================================
# 1. CLI ARGUMENT VALIDATION TESTS
# ==============================================================================

def test_cli_rejects_judge_with_offline_mode():
    with pytest.raises(SystemExit) as exc_info:
        runner.main(["--suite", "rag", "--mode", "offline", "--judge"])
    assert exc_info.value.code == 2


def test_cli_rejects_invalid_top_k_and_missing_dataset(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        runner.main(["--suite", "rag", "--mode", "offline", "--top-k", "0"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        runner.main(["--suite", "rag", "--mode", "offline", "--model", "gemini-2.5-flash"])
    assert exc_info.value.code == 2

    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(SystemExit) as exc_info:
        runner.main(["--suite", "rag", "--mode", "offline", "--dataset", str(missing)])
    assert exc_info.value.code == 2


def test_cli_offline_invocation_writes_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    fake_emb = _DeterministicKeywordEmbedder()

    with patch("evals.rag_evaluator._load_cached_embedder", return_value=fake_emb):
        rc = runner.main(["--suite", "rag", "--mode", "offline", "--output-dir", str(tmp_path)])

    assert rc == 0
    json_files = list(tmp_path.glob("rag_eval_offline_*.json"))
    csv_file = tmp_path / "rag_eval_summary.csv"
    assert len(json_files) == 1
    assert csv_file.exists()


# ==============================================================================
# 2. ISOLATION, CLEANUP, ZERO GEMINI CALLS & PRODUCTION CHROMA PROTECTION
# ==============================================================================

def test_offline_mode_makes_zero_gemini_calls_and_never_touches_prod_chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "should_not_be_used")
    created_persist_dirs = []
    real_vs_init = rag_evaluator.VectorStoreService.__init__

    def _spy_vs_init(self, persist_dir=None, model_name=None):
        created_persist_dirs.append(persist_dir)
        return real_vs_init(self, persist_dir=persist_dir, model_name=model_name)

    with patch("app.services.rag_service.call_gemini", side_effect=AssertionError("Gemini called in offline mode")), \
         patch("app.services.rag_service.generate_text", side_effect=AssertionError("Gateway called in offline mode")), \
         patch("evals.rag_evaluator.generate_text", side_effect=AssertionError("Judge called in offline mode")), \
         patch.object(rag_evaluator.VectorStoreService, "get_instance", side_effect=AssertionError("Production singleton accessed")), \
         patch.object(rag_evaluator.VectorStoreService, "__init__", _spy_vs_init):
        report = rag_evaluator.run_rag_evaluation(
            mode="offline",
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    assert len(created_persist_dirs) == 1
    tmp_eval_dir = created_persist_dirs[0]
    assert tmp_eval_dir != settings.CHROMA_PERSIST_DIR
    assert "codepilot_rag_eval_" in tmp_eval_dir
    # Temp directory must be cleaned up on success
    assert not os.path.exists(tmp_eval_dir)
    assert report["telemetry_summary"] is None
    assert report["judge_summary"] is None


def test_temp_directory_cleaned_up_even_on_failure(tmp_path):
    created_persist_dirs = []
    real_vs_init = rag_evaluator.VectorStoreService.__init__

    def _spy_vs_init(self, persist_dir=None, model_name=None):
        created_persist_dirs.append(persist_dir)
        return real_vs_init(self, persist_dir=persist_dir, model_name=model_name)

    with patch.object(rag_evaluator.VectorStoreService, "__init__", _spy_vs_init), \
         patch("evals.rag_evaluator.answer_question_with_trace", side_effect=RuntimeError("Simulated failure")):
        with pytest.raises(RuntimeError, match="Simulated failure"):
            rag_evaluator.run_rag_evaluation(
                mode="offline",
                output_dir=tmp_path,
                embedder=_DeterministicKeywordEmbedder(),
            )

    assert len(created_persist_dirs) == 1
    assert not os.path.exists(created_persist_dirs[0])


# ==============================================================================
# 3. DETERMINISM & REPORT STRUCTURE (JSON + CSV)
# ==============================================================================

def test_repeated_offline_runs_are_deterministic_and_produce_valid_artifacts(tmp_path):
    fake_emb = _DeterministicKeywordEmbedder()

    r1 = rag_evaluator.run_rag_evaluation(mode="offline", output_dir=tmp_path, embedder=fake_emb)
    r2 = rag_evaluator.run_rag_evaluation(mode="offline", output_dir=tmp_path, embedder=fake_emb)

    assert r1["dataset_version"] == "1.0"
    assert r1["mode"] == "offline"
    assert r1["summary"] == r2["summary"]
    assert r1["cases"] == r2["cases"]

    json_file = Path(r1["artifacts"]["json_report"])
    csv_file = Path(r1["artifacts"]["csv_summary"])
    assert json_file.exists()
    assert csv_file.exists()

    parsed_json = json.loads(json_file.read_text(encoding="utf-8"))
    assert parsed_json["summary"]["total_cases"] == 20
    assert len(parsed_json["cases"]) == 20
    assert "retrieval" in parsed_json["cases"][0]
    assert "answer" in parsed_json["cases"][0]
    # Verify sensitive/production artifacts never appear
    raw_json = json_file.read_text(encoding="utf-8")
    assert "chroma_data" not in raw_json

    with csv_file.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["mode"] == "offline"
    assert rows[0]["total_cases"] == "20"


# ==============================================================================
# 4. LIVE MODE, OPT-IN JUDGE & MISSING TOKEN METADATA AGGREGATION TESTS
# ==============================================================================

def test_live_mode_invokes_gateway_without_judge_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "live_test_key_do_not_leak")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    def _fake_generate_text(**kwargs):
        feature = kwargs.get("feature")
        if feature == "rag_rewrite":
            return LLMGenerationResult(
                text="Stand-alone rewritten question about closures and TCP",
                model_used="gemini-3.5-flash-lite",
                model_version="v1",
                prompt_tokens=20,
                output_tokens=10,
                total_tokens=30,
                latency_ms=15.0,
            )
        return LLMGenerationResult(
            text="Grounded live answer from course notes.",
            model_used="gemini-2.5-flash",
            model_version="v2",
            prompt_tokens=100,
            output_tokens=25,
            total_tokens=125,
            latency_ms=50.0,
        )

    with patch("app.services.rag_service.generate_text", side_effect=_fake_generate_text) as mock_rag_gw, \
         patch("evals.rag_evaluator.generate_text", side_effect=AssertionError("Judge ran without --judge")):
        report = rag_evaluator.run_rag_evaluation(
            mode="live",
            use_judge=False,
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    assert mock_rag_gw.call_count >= 1
    assert report["judge_enabled"] is False
    assert report["judge_summary"] is None
    assert report["telemetry_summary"]["calls_recorded"] >= 1
    assert report["telemetry_summary"]["total_tokens"] > 0
    assert "live_test_key_do_not_leak" not in json.dumps(report)


def test_live_mode_with_opt_in_judge_records_separate_judge_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "live_test_key_abc")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    def _fake_rag_gw(**kwargs):
        if kwargs.get("feature") == "rag_rewrite":
            return LLMGenerationResult(
                text="CLARIFY: Specify which topic?" if "comparing merge sort" in kwargs["prompt"] or "TCP, or UDP" in kwargs["prompt"] else "Merge sort auxiliary space complexity",
                model_used="gemini-3.5-flash-lite",
                prompt_tokens=15,
                output_tokens=8,
                total_tokens=23,
                latency_ms=10.0,
            )
        return LLMGenerationResult(
            text="Standard grounded response referencing corpus facts.",
            model_used="gemini-2.5-flash",
            prompt_tokens=80,
            output_tokens=20,
            total_tokens=100,
            latency_ms=40.0,
        )

    def _fake_judge_gw(**kwargs):
        assert kwargs["feature"] == "rag_eval_judge"
        return LLMGenerationResult(
            text=json.dumps({
                "faithfulness_score": 0.95,
                "relevance_score": 0.90,
                "reasoning": "Supported by retrieved chunks.",
            }),
            model_used="gemini-2.5-flash",
            prompt_tokens=60,
            output_tokens=15,
            total_tokens=75,
            latency_ms=25.0,
        )

    with patch("app.services.rag_service.generate_text", side_effect=_fake_rag_gw), \
         patch("evals.rag_evaluator.generate_text", side_effect=_fake_judge_gw) as mock_judge:
        report = rag_evaluator.run_rag_evaluation(
            mode="live",
            use_judge=True,
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    assert mock_judge.call_count >= 1
    assert report["judge_summary"] is not None
    assert report["judge_summary"]["evaluated_cases"] >= 1
    assert report["judge_summary"]["mean_faithfulness"] == pytest.approx(0.95)
    assert report["judge_summary"]["mean_relevance"] == pytest.approx(0.90)
    assert report["judge_summary"]["telemetry"]["total_tokens"] > 0


def test_token_usage_aggregation_handles_missing_metadata():
    # None usage metadata must NEVER be converted to 0
    missing_only = [
        LLMGenerationResult(
            text="a",
            model_used="gemini-2.5-flash",
            prompt_tokens=None,
            output_tokens=None,
            total_tokens=None,
            thoughts_tokens=None,
            latency_ms=20.0,
        ),
        LLMGenerationResult(
            text="b",
            model_used="gemini-2.5-flash",
            prompt_tokens=None,
            output_tokens=None,
            total_tokens=None,
            thoughts_tokens=None,
            latency_ms=40.0,
        ),
    ]
    agg_missing = rag_evaluator.aggregate_telemetry_summary(missing_only)
    assert agg_missing["calls_recorded"] == 2
    assert agg_missing["calls_with_usage"] == 0
    assert agg_missing["prompt_tokens"] is None
    assert agg_missing["output_tokens"] is None
    assert agg_missing["total_tokens"] is None
    assert agg_missing["thoughts_tokens"] is None
    assert agg_missing["mean_latency_ms"] == 30.0

    # Mixed missing + present only sums genuine observed counts
    mixed = missing_only + [
        LLMGenerationResult(
            text="c",
            model_used="gemini-2.5-flash",
            prompt_tokens=50,
            output_tokens=15,
            total_tokens=65,
            thoughts_tokens=None,
            latency_ms=30.0,
        )
    ]
    agg_mixed = rag_evaluator.aggregate_telemetry_summary(mixed)
    assert agg_mixed["calls_recorded"] == 3
    assert agg_mixed["calls_with_usage"] == 1
    assert agg_mixed["prompt_tokens"] == 50
    assert agg_mixed["output_tokens"] == 15
    assert agg_mixed["total_tokens"] == 65
    assert agg_mixed["thoughts_tokens"] is None

