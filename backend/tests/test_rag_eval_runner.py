import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
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
        ("merge sort",),
        ("binary search",),
        ("hash table",),
        ("translation lookaside buffer", "tlb"),
        ("coffman", "deadlock"),
        ("process heap", "threads"),
        ("three-way handshake", "tcp", "udp"),
        ("dns",),
        ("acid",),
        ("b-tree",),
        ("closure",),
        ("recursion", "recursive functions", "recursive call"),
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
            vec = [1.0 if any(kw in low for kw in kws) else 0.05 for kws in self.KEYWORDS]
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


# ==============================================================================
# 5. CONTROLLED CASE SELECTION (--case-ids AND --limit) TESTS
# ==============================================================================

def test_select_three_explicit_cases_via_cli_and_function(tmp_path):
    fake_emb = _DeterministicKeywordEmbedder()
    with patch("evals.rag_evaluator._load_cached_embedder", return_value=fake_emb):
        rc = runner.main([
            "--suite", "rag",
            "--mode", "offline",
            "--case-ids", "rag_ans_01,rag_conv_01,rag_unans_01",
            "--output-dir", str(tmp_path),
        ])
    assert rc == 0

    json_files = list(tmp_path.glob("rag_eval_offline_*.json"))
    assert len(json_files) == 1
    parsed = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert parsed["summary"]["total_cases"] == 3
    assert parsed["config"]["selected_case_ids"] == ["rag_ans_01", "rag_conv_01", "rag_unans_01"]
    assert [c["case_id"] for c in parsed["cases"]] == ["rag_ans_01", "rag_conv_01", "rag_unans_01"]


def test_select_cases_with_limit_preserves_dataset_order(tmp_path):
    fake_emb = _DeterministicKeywordEmbedder()
    with patch("evals.rag_evaluator._load_cached_embedder", return_value=fake_emb):
        rc = runner.main([
            "--suite", "rag",
            "--mode", "offline",
            "--limit", "3",
            "--output-dir", str(tmp_path),
        ])
    assert rc == 0

    json_files = list(tmp_path.glob("rag_eval_offline_*.json"))
    parsed = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert parsed["summary"]["total_cases"] == 3
    assert parsed["config"]["limit"] == 3
    assert parsed["config"]["selected_case_ids"] == ["rag_ans_01", "rag_ans_02", "rag_ans_03"]


def test_case_selection_validation_errors(tmp_path):
    # Unknown case ID rejected
    with pytest.raises(ValueError, match="Unknown case ID"):
        rag_evaluator.run_rag_evaluation(
            mode="offline",
            case_ids=["rag_ans_01", "does_not_exist_999"],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    # Duplicate case ID rejected (both function and CLI)
    with pytest.raises(ValueError, match="Duplicate case ID"):
        rag_evaluator.run_rag_evaluation(
            mode="offline",
            case_ids=["rag_ans_01", "rag_ans_01"],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )
    with pytest.raises(SystemExit) as exc_dup:
        runner.main(["--suite", "rag", "--mode", "offline", "--case-ids", "rag_ans_01,rag_ans_01"])
    assert exc_dup.value.code == 2

    # Invalid limits (< 1 or bool) rejected
    for bad_limit in (0, -3, True):
        with pytest.raises(ValueError, match="limit"):
            rag_evaluator.run_rag_evaluation(
                mode="offline",
                limit=bad_limit,  # type: ignore
                output_dir=tmp_path,
                embedder=_DeterministicKeywordEmbedder(),
            )
    with pytest.raises(SystemExit) as exc_lim:
        runner.main(["--suite", "rag", "--mode", "offline", "--limit", "0"])
    assert exc_lim.value.code == 2

    # Empty selection rejected (both empty list and empty CLI string / trailing comma)
    with pytest.raises(ValueError, match="cannot be empty"):
        rag_evaluator.run_rag_evaluation(
            mode="offline",
            case_ids=[],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )
    for bad_cli_ids in ("", "   ", "rag_ans_01,"):
        with pytest.raises(SystemExit) as exc_empty:
            runner.main(["--suite", "rag", "--mode", "offline", "--case-ids", bad_cli_ids])
        assert exc_empty.value.code == 2


def test_full_synthetic_corpus_indexed_when_selecting_one_case(tmp_path):
    indexed_chunks_count = 0
    indexed_docs_count = 0
    real_add = rag_evaluator.VectorStoreService.add_document_chunks

    def _spy_add(self, chunks, user_id, document_id, file_size_bytes=0):
        nonlocal indexed_chunks_count, indexed_docs_count
        indexed_docs_count += 1
        indexed_chunks_count += len(chunks)
        return real_add(self, chunks, user_id, document_id, file_size_bytes=file_size_bytes)

    with patch.object(rag_evaluator.VectorStoreService, "add_document_chunks", _spy_add):
        report = rag_evaluator.run_rag_evaluation(
            mode="offline",
            case_ids=["rag_ans_01"],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    assert indexed_docs_count == 5
    assert indexed_chunks_count == 12
    assert report["summary"]["total_cases"] == 1
    assert report["config"]["selected_case_ids"] == ["rag_ans_01"]


def test_default_invocation_evaluates_all_20_cases_and_is_deterministic(tmp_path):
    fake_emb = _DeterministicKeywordEmbedder()
    r1 = rag_evaluator.run_rag_evaluation(mode="offline", output_dir=tmp_path, embedder=fake_emb)
    r2 = rag_evaluator.run_rag_evaluation(mode="offline", output_dir=tmp_path, embedder=fake_emb)

    assert r1["summary"]["total_cases"] == 20
    assert len(r1["config"]["selected_case_ids"]) == 20
    assert r1["summary"] == r2["summary"]
    assert r1["cases"] == r2["cases"]


def test_mocked_live_pilot_subset_limits_gateway_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "mock_live_pilot_key")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    def _fake_rag_gw(**kwargs):
        if kwargs.get("feature") == "rag_rewrite":
            return LLMGenerationResult(
                text="How does a closure retain outer variables after returning?",
                model_used="gemini-2.5-flash",
                prompt_tokens=20,
                output_tokens=10,
                total_tokens=30,
                latency_ms=10.0,
            )
        return LLMGenerationResult(
            text="Grounded response [Document: dsa_algorithms.pdf, Page: 1].",
            model_used="gemini-2.5-flash",
            prompt_tokens=100,
            output_tokens=20,
            total_tokens=120,
            latency_ms=35.0,
        )

    with patch("app.services.rag_service.generate_text", side_effect=_fake_rag_gw) as mock_gw:
        report = rag_evaluator.run_rag_evaluation(
            mode="live",
            case_ids=["rag_ans_01", "rag_conv_01", "rag_unans_01"],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    assert report["summary"]["total_cases"] == 3
    assert report["config"]["selected_case_ids"] == ["rag_ans_01", "rag_conv_01", "rag_unans_01"]
    # With _DeterministicKeywordEmbedder, all 3 cases run generation + 1 rewrite on rag_conv_01 (4 calls vs ~26 for full dataset)
    assert mock_gw.call_count == 4


def test_save_answers_disabled_by_default_and_excluded_from_csv(tmp_path):
    report = rag_evaluator.run_rag_evaluation(
        mode="offline",
        case_ids=["rag_ans_01", "rag_conv_01"],
        output_dir=tmp_path,
        embedder=_DeterministicKeywordEmbedder(),
    )

    assert report["config"]["save_answers"] is False
    for case_entry in report["cases"]:
        assert "generated_answer" not in case_entry
        assert "standalone_query" not in case_entry

    json_data = json.loads(Path(report["artifacts"]["json_report"]).read_text(encoding="utf-8"))
    assert json_data["config"]["save_answers"] is False
    for case_entry in json_data["cases"]:
        assert "generated_answer" not in case_entry
        assert "standalone_query" not in case_entry


def test_save_answers_opt_in_persists_only_in_json_not_csv(tmp_path):
    report = rag_evaluator.run_rag_evaluation(
        mode="offline",
        case_ids=["rag_ans_01", "rag_conv_01"],
        output_dir=tmp_path,
        embedder=_DeterministicKeywordEmbedder(),
        save_answers=True,
    )

    assert report["config"]["save_answers"] is True
    assert len(report["cases"]) == 2
    for case_entry in report["cases"]:
        assert isinstance(case_entry["generated_answer"], str)
        assert len(case_entry["generated_answer"]) > 0
        assert "standalone_query" in case_entry

    json_data = json.loads(Path(report["artifacts"]["json_report"]).read_text(encoding="utf-8"))
    assert all("generated_answer" in c and "standalone_query" in c for c in json_data["cases"])

    # CSV summary must never include generated_answer or standalone_query
    csv_raw = Path(report["artifacts"]["csv_summary"]).read_text(encoding="utf-8")
    csv_header = csv_raw.splitlines()[0]
    assert "generated_answer" not in csv_header
    assert "standalone_query" not in csv_header
    assert "Standard array-based merge sort" not in csv_raw

    # CLI --save-answers flag works end-to-end
    cli_out = tmp_path / "cli_save_answers"
    with patch("evals.runner.run_rag_evaluation", return_value=report) as mock_cli_run:
        rc = runner.main([
            "--suite", "rag",
            "--mode", "offline",
            "--case-ids", "rag_ans_01",
            "--output-dir", str(cli_out),
            "--save-answers",
        ])
    assert rc == 0
    assert mock_cli_run.call_args.kwargs["save_answers"] is True


def test_judge_telemetry_aggregation_preserves_attempt_latencies(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "mock_judge_tel_key")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    def _fake_gw(**kwargs):
        feature = kwargs.get("feature")
        if feature == "rag_eval_judge":
            return LLMGenerationResult(
                text='{"faithfulness_score": 0.9, "relevance_score": 1.0, "reasoning": "Grounded."}',
                model_used="gemini-2.5-pro",
                prompt_tokens=80,
                output_tokens=20,
                total_tokens=100,
                latency_ms=420.0,
                attempt_latency_ms=110.0,
                attempt_latencies_ms=[310.0, 110.0],
                retries=1,
                fallback_used=False,
            )
        return LLMGenerationResult(
            text="Standard array-based merge sort takes O(n log n) time and O(n) auxiliary space [Document: dsa_algorithms.pdf, Page: 1].",
            model_used="gemini-3.5-flash-lite",
            prompt_tokens=120,
            output_tokens=30,
            total_tokens=150,
            latency_ms=55.0,
            attempt_latency_ms=55.0,
            attempt_latencies_ms=[55.0],
            retries=0,
            fallback_used=False,
        )

    with patch("app.services.rag_service.generate_text", side_effect=_fake_gw), \
         patch("evals.rag_evaluator.generate_text", side_effect=_fake_gw):
        report = rag_evaluator.run_rag_evaluation(
            mode="live",
            use_judge=True,
            case_ids=["rag_ans_01"],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    judge_entry = report["cases"][0]["judge"]
    assert judge_entry["telemetry"]["attempt_latency_ms"] == pytest.approx(110.0)
    assert judge_entry["telemetry"]["attempt_latencies_ms"] == pytest.approx([310.0, 110.0])
    assert report["judge_summary"]["telemetry"]["mean_latency_ms"] == pytest.approx(420.0)
    assert report["judge_summary"]["telemetry"]["mean_attempt_latency_ms"] == pytest.approx(110.0)


def test_save_answers_in_mocked_live_mode_and_excluded_from_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "mock_live_save_key")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    def _fake_live_gw(**kwargs):
        if kwargs.get("feature") == "rag_rewrite":
            return LLMGenerationResult(
                text="How does a closure retain access to outer variables after returning?",
                model_used="gemini-3.5-flash-lite",
                prompt_tokens=25,
                output_tokens=12,
                total_tokens=37,
                latency_ms=15.0,
                attempt_latency_ms=15.0,
                attempt_latencies_ms=[15.0],
            )
        return LLMGenerationResult(
            text="A closure retains lexical environment references after returning [Document: programming_fundamentals.pdf, Page: 1].",
            model_used="gemini-3.5-flash-lite",
            prompt_tokens=140,
            output_tokens=28,
            total_tokens=168,
            latency_ms=42.0,
            attempt_latency_ms=42.0,
            attempt_latencies_ms=[42.0],
        )

    fake_emb = _DeterministicKeywordEmbedder()
    with patch("evals.rag_evaluator._load_cached_embedder", return_value=fake_emb), \
         patch("app.services.rag_service.generate_text", side_effect=_fake_live_gw):
        rc = runner.main([
            "--suite", "rag",
            "--mode", "live",
            "--case-ids", "rag_conv_01,rag_ans_01",
            "--output-dir", str(tmp_path),
            "--save-answers",
        ])

    assert rc == 0
    json_files = list(tmp_path.glob("rag_eval_live_*.json"))
    assert len(json_files) == 1
    parsed = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert parsed["config"]["save_answers"] is True
    assert parsed["cases"][0]["standalone_query"] == "How does a closure retain access to outer variables after returning?"
    assert "lexical environment references" in parsed["cases"][0]["generated_answer"]
    assert parsed["telemetry_summary"]["mean_attempt_latency_ms"] is not None

    csv_raw = (tmp_path / "rag_eval_summary.csv").read_text(encoding="utf-8")
    csv_header = csv_raw.splitlines()[0]
    assert "generated_answer" not in csv_header
    assert "standalone_query" not in csv_header
    assert "lexical environment references" not in csv_raw


def test_combined_case_ids_and_limit_preserves_requested_order_and_indexes_full_corpus(tmp_path):
    fake_emb = _DeterministicKeywordEmbedder()
    with patch("evals.rag_evaluator._load_cached_embedder", return_value=fake_emb):
        rc = runner.main([
            "--suite", "rag",
            "--mode", "offline",
            "--case-ids", "rag_conv_01,rag_ans_01,rag_unans_01",
            "--limit", "2",
            "--output-dir", str(tmp_path),
        ])

    assert rc == 0
    json_files = list(tmp_path.glob("rag_eval_offline_*.json"))
    parsed = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert parsed["summary"]["total_cases"] == 2
    assert parsed["config"]["limit"] == 2
    assert parsed["config"]["selected_case_ids"] == ["rag_conv_01", "rag_ans_01"]
    assert [c["case_id"] for c in parsed["cases"]] == ["rag_conv_01", "rag_ans_01"]


def test_failed_generation_captured_in_live_report_and_aggregated_with_success(tmp_path, monkeypatch):
    import httpx
    from types import SimpleNamespace

    obs_log = tmp_path / "prod_observability.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "secret_eval_key_do_not_log")
    monkeypatch.setattr(settings, "GEMINI_REWRITE_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(obs_log))

    clock = {"t": 0.0}

    def fake_perf_counter():
        return clock["t"]

    call_idx = {"n": 0}

    def fake_generate_content(**kwargs):
        call_idx["n"] += 1
        model_name = kwargs["model"]
        # Call 1: rag_ans_01 answer generation (succeeds, 20ms)
        if call_idx["n"] == 1:
            assert model_name == "gemini-3.8-flash"
            clock["t"] += 0.02
            return SimpleNamespace(
                text="Merge sort takes O(n log n) worst-case time and O(n) auxiliary space [Document: dsa_algorithms.pdf, Page: 1].",
                model_version="gemini-3.8-flash",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=100,
                    candidates_token_count=20,
                    total_token_count=120,
                    thoughts_token_count=None,
                ),
            )
        # Call 2: rag_conv_01 query rewrite (succeeds, 10ms)
        if call_idx["n"] == 2:
            assert model_name == "gemini-3.5-flash-lite"
            clock["t"] += 0.01
            return SimpleNamespace(
                text="How does a closure retain outer variables after returning?",
                model_version="gemini-3.5-flash-lite",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=40,
                    candidates_token_count=10,
                    total_token_count=50,
                    thoughts_token_count=None,
                ),
            )
        # Call 3: rag_conv_01 answer generation (times out after 60ms)
        assert model_name == "gemini-3.8-flash"
        clock["t"] += 0.06
        raise httpx.ReadTimeout("Request timed out while reading prompt='SECRET_PROMPT_DO_NOT_LOG'")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = fake_generate_content

    with patch("app.services.llm_gateway.genai.Client", return_value=mock_client), \
         patch("app.services.llm_gateway.time.perf_counter", side_effect=fake_perf_counter):
        report = rag_evaluator.run_rag_evaluation(
            mode="live",
            model="gemini-3.8-flash",
            case_ids=["rag_ans_01", "rag_conv_01"],
            output_dir=tmp_path,
            embedder=_DeterministicKeywordEmbedder(),
        )

    ans_case = next(c for c in report["cases"] if c["case_id"] == "rag_ans_01")
    conv_case = next(c for c in report["cases"] if c["case_id"] == "rag_conv_01")

    assert ans_case["is_error"] is False
    assert ans_case["telemetry"]["generation"]["success"] is True
    assert ans_case["telemetry"]["generation"]["latency_ms"] == pytest.approx(20.0)

    assert conv_case["is_error"] is True
    assert conv_case["telemetry"]["rewriter"]["success"] is True
    assert conv_case["telemetry"]["rewriter"]["model_used"] == "gemini-3.5-flash-lite"
    assert conv_case["telemetry"]["rewriter"]["latency_ms"] == pytest.approx(10.0)

    failed_gen = conv_case["telemetry"]["generation"]
    assert failed_gen is not None
    assert failed_gen["success"] is False
    assert failed_gen["error_category"] == "timeout"
    assert failed_gen["model_used"] == "gemini-3.8-flash"
    assert failed_gen["latency_ms"] == pytest.approx(60.0)
    assert failed_gen["attempt_latency_ms"] == pytest.approx(60.0)
    assert failed_gen["attempt_latencies_ms"] == pytest.approx([60.0])
    assert failed_gen["attempt_count"] == 1
    assert failed_gen["prompt_tokens"] is None
    assert failed_gen["output_tokens"] is None
    assert failed_gen["total_tokens"] is None
    assert failed_gen["thoughts_tokens"] is None

    tel_sum = report["telemetry_summary"]
    assert tel_sum["calls_recorded"] == 3
    assert tel_sum["successful_calls"] == 2
    assert tel_sum["failed_calls"] == 1
    assert tel_sum["calls_with_usage"] == 2
    assert tel_sum["prompt_tokens"] == 140
    assert tel_sum["output_tokens"] == 30
    assert tel_sum["total_tokens"] == 170
    assert tel_sum["thoughts_tokens"] is None
    assert tel_sum["mean_latency_ms"] == pytest.approx(30.0)  # (20 + 10 + 60) / 3
    assert tel_sum["mean_success_latency_ms"] == pytest.approx(15.0)  # (20 + 10) / 2
    assert tel_sum["mean_failure_latency_ms"] == pytest.approx(60.0)
    assert tel_sum["mean_attempt_latency_ms"] == pytest.approx(30.0)
    assert tel_sum["error_categories"] == {"timeout": 1}
    assert tel_sum["models_used"] == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

    # Production observability JSONL recorded all 3 calls with zero content/key leakage
    obs_raw = obs_log.read_text(encoding="utf-8")
    obs_records = [json.loads(line) for line in obs_raw.splitlines()]
    assert len(obs_records) == 3
    assert sum(1 for r in obs_records if not r["success"]) == 1
    assert "SECRET_PROMPT_DO_NOT_LOG" not in obs_raw
    assert "secret_eval_key_do_not_log" not in obs_raw
    assert "Merge sort takes O(n log n)" not in obs_raw
    assert "Closures" not in obs_raw
    assert "Merge sort" not in obs_raw

    # Failed-only aggregation keeps token sums strictly None (never 0)
    failed_only = rag_evaluator.aggregate_telemetry_summary([
        LLMGenerationResult(
            text="",
            model_used="gemini-3.8-flash",
            latency_ms=120000.0,
            attempt_latency_ms=120000.0,
            attempt_latencies_ms=[120000.0],
            success=False,
            error_category="timeout",
        )
    ])
    assert failed_only["calls_recorded"] == 1
    assert failed_only["successful_calls"] == 0
    assert failed_only["failed_calls"] == 1
    assert failed_only["prompt_tokens"] is None
    assert failed_only["output_tokens"] is None
    assert failed_only["total_tokens"] is None
    assert failed_only["thoughts_tokens"] is None
    assert failed_only["mean_latency_ms"] == pytest.approx(120000.0)
    assert failed_only["mean_success_latency_ms"] is None
    assert failed_only["mean_failure_latency_ms"] == pytest.approx(120000.0)

