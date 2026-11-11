from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.schemas.tutor import ChatMessage, DocumentChunk, QueryResponse
from app.services.llm_gateway import LLMGenerationResult
from app.services.rag_service import (
    RAGTrace,
    answer_question,
    answer_question_with_trace,
    call_gemini,
)
from app.services.vector_store import VectorStoreService


class _DeterministicFakeEmbedder:
    """Fast local embedder avoiding network access during unit tests of VectorStoreService."""

    def encode(self, texts, show_progress_bar=False):
        class _VecArray:
            def __init__(self, rows):
                self._rows = rows

            def tolist(self):
                return self._rows

        rows = []
        for t in texts:
            low = t.lower()
            rows.append([
                1.0 if "binary" in low else 0.1,
                1.0 if "merge" in low else 0.1,
                1.0 if "hash" in low else 0.1,
            ])
        return _VecArray(rows)


def test_similarity_search_includes_chunk_id_and_preserves_user_isolation(tmp_path):
    store = VectorStoreService(persist_dir=str(tmp_path / "chroma_eval_test"))
    store._embedder = _DeterministicFakeEmbedder()

    alice_chunk = DocumentChunk(
        id="Algorithms_pdf_p4_c2",
        document_name="Algorithms.pdf",
        page_number=4,
        chunk_index=2,
        text="Binary search runs in O(log n) time on sorted arrays.",
    )
    bob_chunk = DocumentChunk(
        id="Secrets_pdf_p1_c0",
        document_name="Secrets.pdf",
        page_number=1,
        chunk_index=0,
        text="Binary secret belonging strictly to Bob.",
    )

    store.add_document_chunks([alice_chunk], user_id="alice_trace_user", document_id="doc_alice_1")
    store.add_document_chunks([bob_chunk], user_id="bob_trace_user", document_id="doc_bob_1")

    results_alice = store.similarity_search("binary search complexity", user_id="alice_trace_user", top_k=2)
    assert len(results_alice) == 1
    assert results_alice[0]["chunk_id"] == "Algorithms_pdf_p4_c2"
    assert results_alice[0]["document_name"] == "Algorithms.pdf"
    assert results_alice[0]["page_number"] == 4
    assert results_alice[0]["user_id"] == "alice_trace_user"

    # Bob cannot see Alice's chunk and receives only his own chunk_id
    results_bob = store.similarity_search("binary search complexity", user_id="bob_trace_user", top_k=2)
    assert len(results_bob) == 1
    assert results_bob[0]["chunk_id"] == "Secrets_pdf_p1_c0"
    assert results_bob[0]["user_id"] == "bob_trace_user"


class _StubStore:
    def __init__(self, chunks):
        self._chunks = chunks

    def similarity_search(self, query, user_id=None, top_k=4, document_filter=None):
        return self._chunks[:top_k]


def test_trace_captures_standalone_query_and_retrieved_chunks():
    chunks = [
        {
            "chunk_id": "DS_p2_c1",
            "document_name": "DS.pdf",
            "page_number": 2,
            "chunk_index": 1,
            "text": "A stack follows Last-In-First-Out ordering.",
            "similarity": 0.91,
        }
    ]
    store = _StubStore(chunks)
    history = [
        ChatMessage(role="user", content="Tell me about stacks."),
        ChatMessage(role="assistant", content="Stacks store items."),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "What ordering rule does a stack use?"

    def mock_llm(prompt: str) -> str:
        return "A stack uses LIFO ordering [Document: DS.pdf, Page: 2]."

    response, trace = answer_question_with_trace(
        question="What ordering does it use?",
        user_id="trace_user_1",
        vector_store=store,  # type: ignore
        history=history,
        rewrite_callable=mock_rewrite,
        llm_callable=mock_llm,
    )

    assert isinstance(response, QueryResponse)
    assert isinstance(trace, RAGTrace)
    assert trace.standalone_query == "What ordering rule does a stack use?"
    assert len(trace.retrieved_chunks) == 1
    assert trace.retrieved_chunks[0]["chunk_id"] == "DS_p2_c1"
    assert trace.max_similarity == 0.91
    assert trace.threshold_triggered is False
    assert trace.clarification_triggered is False
    # Telemetry via custom callables cannot be fabricated and remains None
    assert trace.rewriter_telemetry is None
    assert trace.generation_telemetry is None


def test_trace_captures_threshold_triggered_decision(monkeypatch):
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", 0.5)
    low_chunks = [
        {
            "chunk_id": "Notes_p1_c0",
            "document_name": "Notes.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Unrelated introductory text.",
            "similarity": 0.22,
        }
    ]
    store = _StubStore(low_chunks)

    response, trace = answer_question_with_trace(
        question="Explain quantum error correction",
        user_id="trace_user_2",
        vector_store=store,  # type: ignore
    )

    assert response.insufficient_context is True
    assert response.citations == []
    assert trace.threshold_triggered is True
    assert trace.max_similarity == 0.22
    assert len(trace.retrieved_chunks) == 1
    assert trace.generation_telemetry is None


def test_trace_records_clarification_path():
    store = _StubStore([])
    history = [
        ChatMessage(role="user", content="We covered sorting."),
        ChatMessage(role="assistant", content="Yes, mergesort and quicksort."),
    ]

    response, trace = answer_question_with_trace(
        question="Show me that",
        user_id="trace_user_3",
        vector_store=store,  # type: ignore
        history=history,
        rewrite_callable=lambda p: "CLARIFY: Did you mean mergesort or quicksort?",
    )

    assert response.insufficient_context is False
    assert "mergesort or quicksort" in response.answer
    assert trace.clarification_triggered is True
    assert trace.standalone_query.startswith("CLARIFY:")
    assert trace.retrieved_chunks == []
    assert trace.threshold_triggered is False
    assert trace.generation_telemetry is None


def test_trace_captures_gateway_telemetry_for_rewriter_and_generation(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    chunks = [
        {
            "chunk_id": "Graphs_p8_c0",
            "document_name": "Graphs.pdf",
            "page_number": 8,
            "chunk_index": 0,
            "text": "BFS explores vertices level by level using a queue.",
            "similarity": 0.93,
        }
    ]
    store = _StubStore(chunks)
    history = [
        ChatMessage(role="user", content="Explain BFS."),
        ChatMessage(role="assistant", content="BFS traverses graphs."),
    ]

    rewrite_gw = LLMGenerationResult(
        text="Which data structure does BFS use?",
        model_used="gemini-3.5-flash-lite",
        model_version="gemini-3.5-flash-lite-001",
        prompt_tokens=40,
        output_tokens=10,
        total_tokens=50,
        thoughts_tokens=None,
        latency_ms=11.5,
        retries=0,
        fallback_used=False,
    )
    gen_gw = LLMGenerationResult(
        text="BFS uses a queue [Document: Graphs.pdf, Page: 8].",
        model_used="gemini-2.5-flash",
        model_version="gemini-2.5-flash-002",
        prompt_tokens=150,
        output_tokens=22,
        total_tokens=180,
        thoughts_tokens=8,
        latency_ms=42.0,
        retries=0,
        fallback_used=False,
    )

    with patch("app.services.rag_service.generate_text", side_effect=[rewrite_gw, gen_gw]) as mock_gen:
        response, trace = answer_question_with_trace(
            question="What structure does it use?",
            user_id="trace_user_4",
            vector_store=store,  # type: ignore
            history=history,
            model="gemini-2.5-flash",
        )

    assert mock_gen.call_count == 2
    assert response.model_used == "gemini-2.5-flash"
    assert len(response.citations) == 1
    assert trace.rewriter_telemetry == rewrite_gw
    assert trace.generation_telemetry == gen_gw
    assert trace.generation_telemetry.prompt_tokens == 150
    assert trace.generation_telemetry.output_tokens == 22
    assert trace.generation_telemetry.thoughts_tokens == 8


def test_answer_question_preserves_query_response_return_and_patchable_call_gemini(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    chunks = [
        {
            "chunk_id": "Trees_p3_c0",
            "document_name": "Trees.pdf",
            "page_number": 3,
            "chunk_index": 0,
            "text": "AVL trees keep balance factors in {-1, 0, 1}.",
            "similarity": 0.90,
        }
    ]
    store = _StubStore(chunks)

    with patch(
        "app.services.rag_service.call_gemini",
        return_value="AVL trees maintain balance factor in {-1, 0, 1} [Document: Trees.pdf, Page: 3].",
    ) as mock_call:
        res = answer_question(
            question="What is the AVL balance factor invariant?",
            user_id="compat_user",
            vector_store=store,  # type: ignore
        )

    mock_call.assert_called_once()
    assert type(res) is QueryResponse
    assert not isinstance(res, tuple)
    assert res.citations[0].page_number == 3


def test_call_gemini_client_and_sleep_fn_injection_preserved(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        Exception("429 RESOURCE_EXHAUSTED: transient"),
        SimpleNamespace(text="Injected success", model_version="gemini-test", usage_metadata=None),
    ]
    mock_sleep = MagicMock()

    text = call_gemini(
        prompt="Hi",
        model="gemini-3.5-flash-lite",
        client=mock_client,
        sleep_fn=mock_sleep,
    )

    assert text == "Injected success"
    assert mock_client.models.generate_content.call_count == 2
    mock_sleep.assert_called_once()


def test_trace_captures_successful_rewrite_and_failed_generation_telemetry(monkeypatch):
    from app.services.rag_service import _llm_trace_slot

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_rag_fail")
    monkeypatch.setattr(settings, "GEMINI_REWRITE_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    chunks = [
        {
            "chunk_id": "PF_p1_c0",
            "document_name": "programming_fundamentals.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Closures retain access to outer lexical environment variables.",
            "similarity": 0.88,
        }
    ]
    store = _StubStore(chunks)
    history = [
        ChatMessage(role="user", content="What is a closure?"),
        ChatMessage(role="assistant", content="A closure bundles a function with scope."),
    ]

    def _client_side_effect(**kwargs):
        if kwargs["model"] == "gemini-3.5-flash-lite":
            return SimpleNamespace(
                text="How does a closure retain outer variables?",
                model_version="gemini-3.5-flash-lite",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=44,
                    candidates_token_count=9,
                    total_token_count=53,
                    thoughts_token_count=None,
                ),
            )
        raise TimeoutError("Read timed out during answer synthesis SECRET_PROMPT_LEAK")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _client_side_effect

    with patch("app.services.llm_gateway.genai.Client", return_value=mock_client):
        response, trace = answer_question_with_trace(
            question="How does it retain outer variables?",
            user_id="trace_user_fail",
            vector_store=store,  # type: ignore
            history=history,
            model="gemini-3.8-flash",
        )

    assert response.is_error is True
    assert trace.rewriter_telemetry is not None
    assert trace.rewriter_telemetry.success is True
    assert trace.rewriter_telemetry.model_used == "gemini-3.5-flash-lite"
    assert trace.rewriter_telemetry.total_tokens == 53

    assert trace.generation_telemetry is not None
    assert trace.generation_telemetry.success is False
    assert trace.generation_telemetry.error_category == "timeout"
    assert trace.generation_telemetry.model_used == "gemini-3.8-flash"
    assert trace.generation_telemetry.prompt_tokens is None
    assert trace.generation_telemetry.output_tokens is None
    assert trace.generation_telemetry.total_tokens is None
    assert trace.generation_telemetry.thoughts_tokens is None
    assert trace.generation_telemetry.latency_ms >= 0.0
    assert trace.generation_telemetry.attempt_latency_ms is not None
    assert len(trace.generation_telemetry.attempt_latencies_ms) == 1
    assert "SECRET_PROMPT_LEAK" not in trace.generation_telemetry.model_dump_json()
    assert _llm_trace_slot.get() is None


def test_filter_settings_validation_and_disable_gap(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("SECONDARY_SIMILARITY_THRESHOLD", raising=False)
    monkeypatch.delenv("RETRIEVAL_SCORE_GAP", raising=False)
    defaults = Settings()
    assert defaults.SECONDARY_SIMILARITY_THRESHOLD == pytest.approx(0.35)
    assert defaults.RETRIEVAL_SCORE_GAP == pytest.approx(0.25)

    monkeypatch.setenv("SECONDARY_SIMILARITY_THRESHOLD", "  ")
    monkeypatch.setenv("RETRIEVAL_SCORE_GAP", "")
    blanks = Settings()
    assert blanks.SECONDARY_SIMILARITY_THRESHOLD == pytest.approx(0.35)
    assert blanks.RETRIEVAL_SCORE_GAP == pytest.approx(0.25)

    # RETRIEVAL_SCORE_GAP <= 0 is valid and disables gap filtering
    monkeypatch.setenv("RETRIEVAL_SCORE_GAP", "0")
    assert Settings().RETRIEVAL_SCORE_GAP == pytest.approx(0.0)
    monkeypatch.setenv("RETRIEVAL_SCORE_GAP", "-0.5")
    assert Settings().RETRIEVAL_SCORE_GAP == pytest.approx(-0.5)

    # Invalid values raise explicit ValueError
    for bad in ("abc", "-0.1", "1.5"):
        monkeypatch.setenv("SECONDARY_SIMILARITY_THRESHOLD", bad)
        with pytest.raises(ValueError, match="SECONDARY_SIMILARITY_THRESHOLD"):
            Settings()
    monkeypatch.delenv("SECONDARY_SIMILARITY_THRESHOLD", raising=False)

    for bad_gap in ("xyz", "1.5"):
        monkeypatch.setenv("RETRIEVAL_SCORE_GAP", bad_gap)
        with pytest.raises(ValueError, match="RETRIEVAL_SCORE_GAP"):
            Settings()


def test_filter_context_chunks_core_and_edge_cases():
    from app.services.rag_service import filter_context_chunks

    # 1. Strong top result + weak sub-threshold and high-gap distractors
    mixed = [
        {"chunk_id": "c1", "document_name": "dsa.pdf", "page_number": 1, "chunk_index": 0, "text": "Merge sort O(n log n).", "similarity": 0.78},
        {"chunk_id": "c2", "document_name": "db.pdf", "page_number": 2, "chunk_index": 1, "text": "B-Tree O(log n).", "similarity": 0.42},  # gap=0.36 > 0.25
        {"chunk_id": "c3", "document_name": "os.pdf", "page_number": 1, "chunk_index": 0, "text": "TLB cache.", "similarity": 0.31},
        {"chunk_id": "c4", "document_name": "net.pdf", "page_number": 1, "chunk_index": 0, "text": "TCP SYN.", "similarity": 0.24},
    ]
    kept = filter_context_chunks(mixed, secondary_threshold=0.35, max_score_gap=0.25)
    assert [c["chunk_id"] for c in kept] == ["c1"]

    # 2. Multiple relevant chunks with close scores (including borderline 0.47 and 0.42 multi-aspect)
    borderline = [
        {"chunk_id": "net_p1", "document_name": "net.pdf", "page_number": 1, "chunk_index": 0, "text": "TCP handshake.", "similarity": 0.47},
        {"chunk_id": "net_p2", "document_name": "net.pdf", "page_number": 2, "chunk_index": 1, "text": "DNS lookup.", "similarity": 0.42},
        {"chunk_id": "noise", "document_name": "dsa.pdf", "page_number": 3, "chunk_index": 2, "text": "Hash table.", "similarity": 0.23},
    ]
    kept_border = filter_context_chunks(borderline, secondary_threshold=0.35, max_score_gap=0.25)
    assert [c["chunk_id"] for c in kept_border] == ["net_p1", "net_p2"]

    # 3. Asymmetric multi-part trade-off: gap=0.25 drops 0.50 (gap=0.35), gap<=0 keeps only threshold >= 0.35
    asymmetric = [
        {"chunk_id": "part_a", "document_name": "os.pdf", "page_number": 1, "chunk_index": 0, "text": "Virtual memory.", "similarity": 0.85},
        {"chunk_id": "part_b", "document_name": "os.pdf", "page_number": 2, "chunk_index": 1, "text": "Deadlock conditions.", "similarity": 0.50},
        {"chunk_id": "weak", "document_name": "net.pdf", "page_number": 1, "chunk_index": 0, "text": "HTTP 404.", "similarity": 0.20},
    ]
    assert [c["chunk_id"] for c in filter_context_chunks(asymmetric, secondary_threshold=0.35, max_score_gap=0.25)] == ["part_a"]
    assert [c["chunk_id"] for c in filter_context_chunks(asymmetric, secondary_threshold=0.35, max_score_gap=0.0)] == ["part_a", "part_b"]
    assert [c["chunk_id"] for c in filter_context_chunks(asymmetric, secondary_threshold=0.35, max_score_gap=-1.0)] == ["part_a", "part_b"]

    # 4. Empty list
    assert filter_context_chunks([]) == []

    # 5. Duplicates (by chunk_id AND by fallback metadata/text) and unsorted input + missing similarity
    unsorted_dups = [
        {"document_name": "a.pdf", "page_number": 1, "text": "Low noise", "similarity": 0.20},
        {"document_name": "a.pdf", "page_number": 2, "text": "No score", "similarity": None},
        {"chunk_id": "dup_id", "document_name": "b.pdf", "page_number": 1, "chunk_index": 0, "text": "Top A", "similarity": 0.70},
        {"chunk_id": "dup_id", "document_name": "b.pdf", "page_number": 1, "chunk_index": 0, "text": "Top A", "similarity": 0.90},
        {"document_name": "c.pdf", "page_number": 3, "text": "Meta dup B", "similarity": 0.80},
        {"document_name": "c.pdf", "page_number": 3, "text": "Meta dup B", "similarity": 0.79},
    ]
    deduped = filter_context_chunks(unsorted_dups, secondary_threshold=0.35, max_score_gap=0.25)
    assert len(deduped) == 2
    assert deduped[0]["chunk_id"] == "dup_id"
    assert deduped[0]["similarity"] == 0.90
    assert deduped[1]["text"] == "Meta dup B"
    assert deduped[1]["similarity"] == 0.80


def test_trace_preserves_raw_chunks_and_filters_prompt_and_fallback_citations(tmp_path):
    store = VectorStoreService(persist_dir=str(tmp_path / "chroma_filter_isolation"))
    store._embedder = _DeterministicFakeEmbedder()

    alice_strong = DocumentChunk(
        id="DSA_p1_c0",
        document_name="DSA.pdf",
        page_number=1,
        chunk_index=0,
        text="Binary search requires a sorted array and runs in O(log n).",
    )
    alice_weak = DocumentChunk(
        id="Noise_p4_c1",
        document_name="Noise.pdf",
        page_number=4,
        chunk_index=1,
        text="Completely unrelated cooking notes about sourdough bread.",
    )
    bob_chunk = DocumentChunk(
        id="Bob_p1_c0",
        document_name="BobSecret.pdf",
        page_number=1,
        chunk_index=0,
        text="Binary search secret belonging to Bob.",
    )
    store.add_document_chunks([alice_strong, alice_weak], user_id="alice_filter", document_id="doc_a")
    store.add_document_chunks([bob_chunk], user_id="bob_filter", document_id="doc_b")

    seen_prompts = []

    def mock_llm_no_tags(prompt: str) -> str:
        seen_prompts.append(prompt)
        # Intentionally omit [Document: ..., Page: ...] tags to exercise fallback citations
        return "Binary search runs in O(log n) time on sorted arrays."

    response, trace = answer_question_with_trace(
        question="What is binary search complexity?",
        user_id="alice_filter",
        vector_store=store,
        top_k=4,
        llm_callable=mock_llm_no_tags,
    )

    assert len(seen_prompts) == 1
    assert "Binary search requires a sorted array" in seen_prompts[0]
    assert "sourdough bread" not in seen_prompts[0]
    assert "BobSecret" not in seen_prompts[0]

    # trace.retrieved_chunks preserves raw Chroma results; trace.context_chunks holds filtered LLM context
    assert len(trace.retrieved_chunks) == 2
    assert len(trace.context_chunks) == 1
    assert trace.context_chunks[0]["document_name"] == "DSA.pdf"
    assert response.retrieved_chunks_count == 1
    assert [c.document_name for c in response.citations] == ["DSA.pdf"]

