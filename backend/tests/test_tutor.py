import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.services.pdf_service import validate_pdf, chunk_document
from app.schemas.tutor import DocumentChunk, ChatMessage
from app.services.rag_service import (
    answer_question, 
    build_citations, 
    build_context_block,
    extract_and_prioritize_citations,
    rewrite_query,
    call_gemini,
    is_quota_exhausted_error,
    is_transient_rate_limit_error,
    extract_retry_delay_seconds,
)
from app.core.config import settings
from app.services import model_service

client = TestClient(app)

# -----------------------------------------------------------------------------
# 1. PDF Validation Tests
# -----------------------------------------------------------------------------
def test_validate_pdf_invalid_extension():
    with pytest.raises(ValueError, match="Only PDF documents"):
        validate_pdf(b"%PDF-1.4 sample", "notes.txt")

def test_validate_pdf_empty_file():
    with pytest.raises(ValueError, match="empty"):
        validate_pdf(b"", "empty.pdf")

def test_validate_pdf_invalid_header():
    with pytest.raises(ValueError, match="lacks standard PDF header"):
        validate_pdf(b"NOT_A_PDF_CONTENT", "corrupt.pdf")

def test_validate_pdf_valid_header():
    # Should not raise any exception
    validate_pdf(b"%PDF-1.4 minimal binary data", "valid.pdf")

# -----------------------------------------------------------------------------
# 2. Text Chunking & Metadata Preservation Tests
# -----------------------------------------------------------------------------
def test_chunk_document_preserves_metadata():
    pages = [
        (1, "Binary search runs in O(log n) time. It requires a sorted array to divide the search space in half each step."),
        (2, "Merge sort divides the list into halves, recursively sorts them, and merges the sorted sublists in O(n log n) time."),
    ]
    chunks = chunk_document(pages, "Algorithms_Note.pdf", chunk_size=80, chunk_overlap=20)
    
    assert len(chunks) >= 2
    for chunk in chunks:
        assert isinstance(chunk, DocumentChunk)
        assert chunk.document_name == "Algorithms_Note.pdf"
        assert chunk.page_number in (1, 2)
        assert chunk.chunk_index >= 0
        assert len(chunk.text) > 0
        assert chunk.id.startswith("Algorithms_Note_pdf_p")

def test_chunk_document_handles_long_unbroken_text():
    # Test handling of an unbroken sequence
    long_text = "word " * 150
    pages = [(1, long_text)]
    chunks = chunk_document(pages, "LongDoc.pdf", chunk_size=100, chunk_overlap=20)
    assert len(chunks) > 1
    assert all(c.page_number == 1 for c in chunks)

# -----------------------------------------------------------------------------
# 3. RAG Pipeline Context Construction & Citation Tests
# -----------------------------------------------------------------------------
def test_build_citations():
    retrieved = [
        {"document_name": "DataStructures.pdf", "page_number": 3, "text": "An AVL tree is a self-balancing binary search tree.", "similarity": 0.85},
        {"document_name": "DataStructures.pdf", "page_number": 3, "text": "Duplicate page snippet.", "similarity": 0.82},
        {"document_name": "DataStructures.pdf", "page_number": 5, "text": "Red-Black tree rotations guarantee logarithmic height.", "similarity": 0.79},
    ]
    citations = build_citations(retrieved)
    # Deduplication per (doc, page)
    assert len(citations) == 2
    assert citations[0].document_name == "DataStructures.pdf"
    assert citations[0].page_number == 3
    assert citations[1].page_number == 5

def test_build_context_block_formats_xml():
    retrieved = [
        {"document_name": "OS.pdf", "page_number": 12, "text": "Virtual memory provides an idealized abstraction of storage."},
    ]
    block = build_context_block(retrieved)
    assert "<reference_materials>" in block
    assert "</reference_materials>" in block
    assert "--- Document: OS.pdf | Page: 12 ---" in block
    assert "Virtual memory provides" in block

def test_extract_and_prioritize_citations():
    retrieved = [
        {"document_name": "JS_Learn.pdf", "page_number": 3, "text": "Hoisting snippet."},
        {"document_name": "JS_Learn.pdf", "page_number": 28, "text": "IIFE snippet."},
        {"document_name": "JS_Learn.pdf", "page_number": 36, "text": "Objects snippet."},
    ]
    # Answer only cites Page 3
    answer = "Hoisting is moving declarations [Document: JS_Learn.pdf, Page: 3]."
    citations = extract_and_prioritize_citations(answer, retrieved, insufficient_context=False)
    assert len(citations) == 1
    assert citations[0].document_name == "JS_Learn.pdf"
    assert citations[0].page_number == 3
    assert "Hoisting" in citations[0].snippet

def test_extract_and_prioritize_citations_insufficient_context_returns_empty():
    retrieved = [
        {"document_name": "JS_Learn.pdf", "page_number": 3, "text": "Hoisting snippet."},
    ]
    citations = extract_and_prioritize_citations("I cannot find sufficient evidence.", retrieved, insufficient_context=True)
    assert len(citations) == 0

def test_extract_and_prioritize_citations_does_not_invent_fake_pages():
    retrieved = [
        {"document_name": "JS_Learn.pdf", "page_number": 3, "text": "Hoisting snippet."},
    ]
    # LLM hallucinates Page 99 which is not in retrieved chunks
    answer = "Hallucinated fact [Document: JS_Learn.pdf, Page: 99]."
    citations = extract_and_prioritize_citations(answer, retrieved, insufficient_context=False)
    # Never invents fake page 99; falls back to verified retrieved chunk
    assert len(citations) == 1
    assert citations[0].page_number == 3

# -----------------------------------------------------------------------------
# 4. RAG Mocked Answer Generation Tests
# -----------------------------------------------------------------------------
class MockVectorStore:
    def __init__(self, chunks):
        self.chunks = chunks

    def similarity_search(self, query, top_k=4, document_filter=None):
        return self.chunks

def test_answer_question_with_grounded_mock_llm():
    mock_chunks = [
        {
            "text": "QuickSort has an average time complexity of O(n log n) and a worst case of O(n^2).",
            "document_name": "Sorting.pdf",
            "page_number": 14,
            "similarity": 0.88,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def mock_llm(prompt: str) -> str:
        assert "<reference_materials>" in prompt
        assert "QuickSort" in prompt
        return "QuickSort runs in average O(n log n) time [Document: Sorting.pdf, Page: 14]."

    response = answer_question(
        question="What is the average time complexity of QuickSort?",
        vector_store=mock_store,
        llm_callable=mock_llm,
    )

    assert not response.insufficient_context
    assert "QuickSort runs in average O(n log n) time" in response.answer
    assert len(response.citations) == 1
    assert response.citations[0].document_name == "Sorting.pdf"
    assert response.citations[0].page_number == 14

def test_answer_question_empty_context():
    mock_store = MockVectorStore([])
    response = answer_question(
        question="Explain quantum computing.",
        vector_store=mock_store,
    )
    assert response.insufficient_context
    assert "cannot find sufficient evidence" in response.answer.lower()
    assert len(response.citations) == 0

def test_answer_question_gemini_error_preserves_citations():
    mock_chunks = [
        {
            "text": "Hoisting is JavaScript's default behavior of moving declarations to the top.",
            "document_name": "JS_Notes.pdf",
            "page_number": 3,
            "similarity": 0.90,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def failing_llm(prompt: str) -> str:
        raise RuntimeError("The configured AI model 'gemini-1.5-flash' was not found.")

    response = answer_question(
        question="What is hoisting?",
        vector_store=mock_store,
        llm_callable=failing_llm,
    )

    assert "Error communicating with AI model" in response.answer
    assert "gemini-1.5-flash" in response.answer
    assert len(response.citations) == 1
    assert response.citations[0].document_name == "JS_Notes.pdf"
    assert response.citations[0].page_number == 3

# -----------------------------------------------------------------------------
# 5. Gemini SDK Integration & Mock Unit Tests
# -----------------------------------------------------------------------------
def test_call_gemini_missing_api_key():
    with patch.object(settings, "GEMINI_API_KEY", ""):
        with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
            call_gemini("Test prompt")

def test_call_gemini_with_mock_client():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "JavaScript hoisting moves declarations to the top."
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(settings, "GEMINI_API_KEY", "test_key_abc123"):
        result = call_gemini(
            prompt="Explain hoisting", 
            model="gemini-3.5-flash", 
            client=mock_client
        )

    assert result == "JavaScript hoisting moves declarations to the top."
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-3.5-flash"
    assert call_kwargs["contents"] == "Explain hoisting"

def test_call_gemini_model_not_found_clean_error():
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("404 NOT_FOUND. models/gemini-1.5-flash is not found")

    with patch.object(settings, "GEMINI_API_KEY", "test_key_abc123"):
        with pytest.raises(RuntimeError) as exc_info:
            call_gemini("Test prompt", model="gemini-1.5-flash", client=mock_client)

    assert "was not found" in str(exc_info.value)
    assert "GEMINI_MODEL" in str(exc_info.value)

def test_call_gemini_rate_limit_clean_error():
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED. Quota exceeded")

    with patch.object(settings, "GEMINI_API_KEY", "test_key_abc123"):
        with pytest.raises(RuntimeError) as exc_info:
            call_gemini("Test prompt", client=mock_client)

    assert "daily quota exceeded" in str(exc_info.value).lower() or "rate limit" in str(exc_info.value).lower()

def test_call_gemini_fallback_on_unavailable():
    mock_client = MagicMock()
    # First call on primary model fails with 503, fallback call succeeds
    mock_success = MagicMock()
    mock_success.text = "Fallback successful response"
    mock_client.models.generate_content.side_effect = [
        Exception("503 UNAVAILABLE. High demand"),
        mock_success,
    ]

    with patch.object(settings, "GEMINI_API_KEY", "test_key_abc123"):
        res = call_gemini("Test prompt", model="gemini-3.8-flash", client=mock_client)

    assert res == "Fallback successful response"
    assert mock_client.models.generate_content.call_count == 2

# -----------------------------------------------------------------------------
# 6. API Route Integration Tests
# -----------------------------------------------------------------------------
def test_list_documents_endpoint():
    response = client.get("/api/tutor/documents")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "total_documents" in data

def test_upload_invalid_file_type():
    response = client.post(
        "/api/tutor/upload",
        files={"file": ("code.py", b"print('hello')", "text/x-python")},
    )
    assert response.status_code == 400
    assert "Only PDF documents" in response.json()["detail"]

def test_upload_corrupt_pdf():
    response = client.post(
        "/api/tutor/upload",
        files={"file": ("fake.pdf", b"NOT_A_REAL_PDF", "application/pdf")},
    )
    assert response.status_code == 400
    assert "Invalid PDF format" in response.json()["detail"]

def test_query_validation():
    # Question too short
    response = client.post("/api/tutor/query", json={"question": "a"})
    assert response.status_code == 422

# -----------------------------------------------------------------------------
# 7. End-to-End Upload, Retrieval & Cleanup Test
# -----------------------------------------------------------------------------
def _create_sample_pdf(text: str) -> bytes:
    stream_content = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin1")
    stream_len = len(stream_content)
    pdf = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {stream_len} >>
stream
{stream_content.decode("latin1")}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000234 00000 n 
0000000300 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
365
%%EOF""".encode("latin1")
    return pdf

def test_e2e_pdf_upload_indexing_and_query():
    pdf_content = _create_sample_pdf(
        "Binary search operates in logarithmic time O(log n). It repeatedly divides the search space in half."
    )
    doc_name = "e2e_binary_search_syllabus.pdf"

    # 1. Upload
    upload_res = client.post(
        "/api/tutor/upload",
        files={"file": (doc_name, pdf_content, "application/pdf")},
    )
    assert upload_res.status_code == 201
    upload_data = upload_res.json()
    assert upload_data["status"] == "success"
    assert upload_data["document"]["document_name"] == doc_name
    assert upload_data["document"]["total_chunks"] >= 1

    # 2. List documents
    list_res = client.get("/api/tutor/documents")
    assert list_res.status_code == 200
    doc_names = [d["document_name"] for d in list_res.json()["documents"]]
    assert doc_name in doc_names

    # 3. Query with mocked call_gemini to guarantee deterministic test execution without consuming live quota
    with patch("app.services.rag_service.call_gemini") as mock_gemini:
        mock_gemini.return_value = "Binary search runs in O(log n) time [Document: e2e_binary_search_syllabus.pdf, Page: 1]."
        query_res = client.post(
            "/api/tutor/query",
            json={"question": "What is the time complexity of binary search?", "document_filter": doc_name},
        )
        assert query_res.status_code == 200
        query_data = query_res.json()
        assert query_data["retrieved_chunks_count"] >= 1
        assert len(query_data["citations"]) >= 1
        assert query_data["citations"][0]["document_name"] == doc_name
        assert query_data["citations"][0]["page_number"] == 1
        assert "Binary search runs in O(log n) time" in query_data["answer"]

    # 4. Cleanup
    del_res = client.delete(f"/api/tutor/documents/{doc_name}")
    assert del_res.status_code == 200

# -----------------------------------------------------------------------------
# 8. Conversation-Aware RAG Tests
# -----------------------------------------------------------------------------
def test_conversational_rag_normal_question():
    """1. A normal question without prior history."""
    mock_store = MockVectorStore([
        {
            "text": "An IIFE creates a private scope immediately in JavaScript.",
            "document_name": "JS.pdf",
            "page_number": 26,
            "similarity": 0.89,
        }
    ])
    def mock_llm(prompt: str) -> str:
        return "An IIFE creates private scope [Document: JS.pdf, Page: 26]."

    response = answer_question(
        question="What is an IIFE in JavaScript?",
        history=[],
        vector_store=mock_store,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert response.standalone_query == "What is an IIFE in JavaScript?"
    assert len(response.citations) == 1
    assert response.citations[0].page_number == 26

def test_conversational_rag_follow_up_why_useful():
    """2. A follow-up such as 'Why is that useful?'."""
    mock_store = MockVectorStore([
        {
            "text": "IIFEs prevent polluting global scope and protect private state.",
            "document_name": "JS.pdf",
            "page_number": 26,
            "similarity": 0.87,
        }
    ])
    history = [
        ChatMessage(role="user", content="What is an IIFE in JavaScript?"),
        ChatMessage(role="assistant", content="An IIFE stands for Immediately Invoked Function Expression [Document: JS.pdf, Page: 26]."),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "Why are Immediately Invoked Function Expressions (IIFE) useful in JavaScript?"

    def mock_llm(prompt: str) -> str:
        assert "<conversation_history>" in prompt
        assert "prevent polluting global scope" in prompt
        return "IIFEs are useful because they prevent polluting global scope [Document: JS.pdf, Page: 26]."

    response = answer_question(
        question="Why is that useful?",
        history=history,
        vector_store=mock_store,
        rewrite_callable=mock_rewrite,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert "IIFE" in response.standalone_query
    assert "prevent polluting global scope" in response.answer
    assert len(response.citations) == 1
    assert response.citations[0].page_number == 26

def test_conversational_rag_follow_up_show_another_example():
    """3. A follow-up such as 'Show me another example.'."""
    mock_store = MockVectorStore([
        {
            "text": "Here is an IIFE example: (function() { let counter = 0; })();",
            "document_name": "JS.pdf",
            "page_number": 28,
            "similarity": 0.91,
        }
    ])
    history = [
        ChatMessage(role="user", content="What is an IIFE in JavaScript?"),
        ChatMessage(role="assistant", content="An IIFE executes immediately: (function(){})();"),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "Show another code example of an IIFE in JavaScript"

    def mock_llm(prompt: str) -> str:
        return "Here is another example of an IIFE: `(function(){ let counter = 0; })();` [Document: JS.pdf, Page: 28]."

    response = answer_question(
        question="Show me another example.",
        history=history,
        vector_store=mock_store,
        rewrite_callable=mock_rewrite,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert "IIFE" in response.standalone_query
    assert "Page: 28" in response.answer
    assert response.citations[0].page_number == 28

def test_conversational_rag_topic_change():
    """4. A topic change should not inherit prior topic bias."""
    mock_store = MockVectorStore([
        {
            "text": "Hoisting in JavaScript prepares memory by moving declarations to top.",
            "document_name": "JS.pdf",
            "page_number": 3,
            "similarity": 0.88,
        }
    ])
    history = [
        ChatMessage(role="user", content="What is an IIFE in JavaScript?"),
        ChatMessage(role="assistant", content="An IIFE creates private scope immediately."),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "What is hoisting?"

    def mock_llm(prompt: str) -> str:
        assert "Hoisting in JavaScript" in prompt
        return "Hoisting moves declarations to the top [Document: JS.pdf, Page: 3]."

    response = answer_question(
        question="What is hoisting?",
        history=history,
        vector_store=mock_store,
        rewrite_callable=mock_rewrite,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert response.standalone_query == "What is hoisting?"
    assert "Hoisting moves declarations" in response.answer
    assert response.citations[0].page_number == 3

def test_conversational_rag_unsupported_follow_up():
    """5. An unsupported follow-up where document context is insufficient."""
    mock_store = MockVectorStore([
        {
            "text": "Basic web styling notes.",
            "document_name": "JS.pdf",
            "page_number": 1,
            "similarity": 0.15,
        }
    ])
    history = [
        ChatMessage(role="user", content="What is an IIFE in JavaScript?"),
        ChatMessage(role="assistant", content="An IIFE creates private scope."),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "How to configure Kubernetes pods using JavaScript IIFE?"

    response = answer_question(
        question="Can it configure Kubernetes pods in cluster?",
        history=history,
        vector_store=mock_store,
        rewrite_callable=mock_rewrite,
    )
    assert response.insufficient_context
    assert "cannot find sufficient evidence" in response.answer.lower()
    assert len(response.citations) == 0

def test_conversational_rag_reset_conversation():
    """6. Resetting the conversation clears history state."""
    history = [
        ChatMessage(role="user", content="What is an IIFE?"),
        ChatMessage(role="assistant", content="An IIFE creates private scope."),
    ]
    # Simulate client clearing/resetting conversation
    history.clear()
    assert len(history) == 0

    mock_store = MockVectorStore([
        {
            "text": "Binary search divides the search space in log(n) time.",
            "document_name": "Algorithms.pdf",
            "page_number": 5,
            "similarity": 0.92,
        }
    ])
    def mock_llm(prompt: str) -> str:
        assert "<conversation_history>" not in prompt
        return "Binary search runs in O(log n) time [Document: Algorithms.pdf, Page: 5]."

    response = answer_question(
        question="What is binary search?",
        history=history,
        vector_store=mock_store,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert response.standalone_query == "What is binary search?"
    assert response.citations[0].page_number == 5

# -----------------------------------------------------------------------------
# 9. Rate Limits, Quota Distinctions & Robust Error Recovery Tests
# -----------------------------------------------------------------------------
def test_conversational_rag_clarification_on_ambiguous():
    """Rewriter detects genuine ambiguity and asks for clarification without failing or fabricating context."""
    mock_store = MockVectorStore([])
    history = [
        ChatMessage(role="user", content="I want to learn about sorting."),
        ChatMessage(role="assistant", content="We have materials on quicksort and mergesort."),
    ]
    def mock_rewrite(prompt: str) -> str:
        return "CLARIFY: Could you specify whether you would like an example of Quicksort or Mergesort?"

    response = answer_question(
        question="Show me an example.",
        history=history,
        vector_store=mock_store,
        rewrite_callable=mock_rewrite,
    )
    assert not response.insufficient_context
    assert not response.is_error
    assert "Could you specify" in response.answer
    assert response.standalone_query.startswith("CLARIFY:")

def test_error_distinction_quota_vs_rate_limit():
    """Verify accurate separation of daily quota exhaustion vs transient rate limits."""
    quota_err = Exception("429 RESOURCE_EXHAUSTED Quota exceeded for quota metric 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'")
    transient_err = Exception("429 Too Many Requests: Rate limit exceeded, retry in 2s")
    generic_err = Exception("500 Internal Server Error")

    assert is_quota_exhausted_error(quota_err) is True
    assert is_transient_rate_limit_error(quota_err) is False

    assert is_quota_exhausted_error(transient_err) is False
    assert is_transient_rate_limit_error(transient_err) is True

    assert is_quota_exhausted_error(generic_err) is False
    assert is_transient_rate_limit_error(generic_err) is False

def test_extract_retry_delay_seconds():
    """Verify parsing of retryDelay from provider error payloads."""
    err_json = Exception("RESOURCE_EXHAUSTED: {'details': [{'@type': 'type.googleapis.com', 'retryDelay': '3.5s'}]}")
    err_text = Exception("Rate limited. Please retry in 4.2s.")
    err_none = Exception("Standard error with no delay specified")

    assert extract_retry_delay_seconds(err_json) == 3.5
    assert extract_retry_delay_seconds(err_text) == 4.2
    assert extract_retry_delay_seconds(err_none) is None

def test_call_gemini_transient_rate_limit_retry_success():
    """Verify call_gemini retries transient 429 with backoff and succeeds."""
    mock_client = MagicMock()
    transient_exc = Exception("429 RESOURCE_EXHAUSTED: Rate limit exceeded")
    mock_success = MagicMock()
    mock_success.text = "Grounded answer after retry"

    mock_client.models.generate_content.side_effect = [transient_exc, mock_success]
    mock_sleep = MagicMock()

    with patch.object(settings, "GEMINI_API_KEY", "test_key_123"):
        result = call_gemini(
            prompt="Explain closures",
            model="gemini-3.5-flash-lite",
            client=mock_client,
            sleep_fn=mock_sleep,
        )

    assert result == "Grounded answer after retry"
    assert mock_client.models.generate_content.call_count == 2
    mock_sleep.assert_called_once()
    # Backoff sleep should be around 1-2 seconds
    sleep_val = mock_sleep.call_args[0][0]
    assert 1.0 <= sleep_val <= 3.0

def test_call_gemini_quota_exhausted_fails_fast_no_infinite_loop():
    """Verify call_gemini does not sleep in loops when daily quota is exhausted."""
    mock_client = MagicMock()
    quota_exc = Exception("429 RESOURCE_EXHAUSTED: quota exceeded per day")
    mock_client.models.generate_content.side_effect = quota_exc
    mock_sleep = MagicMock()

    with patch.object(settings, "GEMINI_API_KEY", "test_key_123"):
        with pytest.raises(RuntimeError) as exc_info:
            call_gemini(
                prompt="Explain closures",
                model="gemini-3.5-flash-lite",
                client=mock_client,
                sleep_fn=mock_sleep,
            )

    assert "daily quota exceeded" in str(exc_info.value).lower()
    # Sleep should never have been called because quota exhaustion is non-transient
    mock_sleep.assert_not_called()

def test_answer_question_gemini_failure_preserves_citations_and_sets_is_error():
    """Verify that provider failure preserves retrieved chunks, flags is_error, and NEVER marks insufficient_context."""
    mock_chunks = [
        {
            "text": "Hoisting prepares memory before running code.",
            "document_name": "JS_Learn.pdf",
            "page_number": 3,
            "similarity": 0.95,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def failing_llm(prompt: str) -> str:
        raise RuntimeError("Gemini API daily quota exceeded for this model tier.")

    response = answer_question(
        question="What is hoisting?",
        vector_store=mock_store,
        llm_callable=failing_llm,
    )

    assert response.is_error is True
    assert response.insufficient_context is False  # CRITICAL: Never convert provider failure to insufficient context
    assert len(response.citations) == 1
    assert response.citations[0].document_name == "JS_Learn.pdf"
    assert response.citations[0].page_number == 3
    assert "Gemini API daily quota exceeded" in response.answer

# -----------------------------------------------------------------------------
# 10. Dynamic Gemini Model Selection & Routing Tests
# -----------------------------------------------------------------------------
def test_list_models_endpoint():
    """1. Test listing available models through the API endpoint."""
    response = client.get("/api/tutor/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert "default_model" in data
    assert "active_routing" in data
    assert len(data["models"]) >= 1
    assert data["active_routing"]["rewrite"] is not None
    # Check model schema
    sample_model = data["models"][0]
    assert "id" in sample_model
    assert "display_name" in sample_model
    assert "category" in sample_model
    assert sample_model["category"] in ["fast", "balanced", "reasoning", "preview", "general"]

def test_model_discovery_filters_non_generate_content():
    """Verify discovery filters models to only those supporting generateContent."""
    mock_client = MagicMock()
    m1 = MagicMock()
    m1.name = "models/gemini-2.5-flash"
    m1.display_name = "Gemini 2.5 Flash"
    m1.description = "Balanced model"
    m1.supported_generation_methods = ["generateContent"]

    m2 = MagicMock()
    m2.name = "models/gemini-embedding-001"
    m2.display_name = "Gemini Embedding"
    m2.description = "Embeddings model"
    m2.supported_generation_methods = ["embedContent"]

    m3 = MagicMock()
    m3.name = "models/gemini-3.8-flash-tts"
    m3.display_name = "Gemini TTS"
    m3.description = "TTS model"
    m3.supported_generation_methods = ["generateContent"]  # TTS keyword should be filtered

    mock_client.models.list.return_value = [m1, m2, m3]

    with patch.object(settings, "GEMINI_API_KEY", "test_key_xyz"):
        discovered = model_service.discover_models_from_api(client=mock_client)

    ids = [m.id for m in discovered]
    assert "gemini-2.5-flash" in ids
    assert "gemini-embedding-001" not in ids
    assert "gemini-3.8-flash-tts" not in ids

def test_select_supported_model_in_query():
    """2 & 3. Select a supported model and send a RAG question."""
    mock_chunks = [
        {
            "text": "Depth-first search uses a stack data structure.",
            "document_name": "Graph_Algorithms.pdf",
            "page_number": 8,
            "similarity": 0.91,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def mock_llm(prompt: str) -> str:
        return "DFS utilizes a stack [Document: Graph_Algorithms.pdf, Page: 8]."

    response = answer_question(
        question="How does DFS explore nodes?",
        vector_store=mock_store,
        llm_callable=mock_llm,
        model="gemini-2.5-flash",
    )
    assert not response.insufficient_context
    assert not response.is_error
    assert response.model_used == "gemini-2.5-flash"
    assert len(response.citations) == 1
    assert response.citations[0].page_number == 8

def test_unsupported_model_rejected():
    """5. Unsupported model ID is rejected with 400 Bad Request."""
    response = client.post(
        "/api/tutor/query",
        json={
            "question": "Explain topological sort",
            "model": "unsupported-hallucinated-model-999"
        }
    )
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"].lower()

def test_switching_models_during_conversation():
    """4 & 7. Switching models during conversation preserves context and citations."""
    mock_chunks = [
        {
            "text": "An adjacency matrix represents graph edges as a 2D array.",
            "document_name": "Graphs.pdf",
            "page_number": 4,
            "similarity": 0.92,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    # Turn 1: Asked with gemini-3.5-flash-lite
    def mock_llm_1(prompt: str) -> str:
        return "An adjacency matrix is a 2D grid [Document: Graphs.pdf, Page: 4]."

    turn_1 = answer_question(
        question="What is an adjacency matrix?",
        history=[],
        vector_store=mock_store,
        llm_callable=mock_llm_1,
        model="gemini-3.5-flash-lite",
    )
    assert turn_1.model_used == "gemini-3.5-flash-lite"
    assert turn_1.citations[0].page_number == 4

    # Turn 2: User switches to gemini-2.5-pro for deeper follow-up
    history = [
        ChatMessage(role="user", content="What is an adjacency matrix?"),
        ChatMessage(role="assistant", content=turn_1.answer),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "What are the space complexity trade-offs of an adjacency matrix in graphs?"

    def mock_llm_2(prompt: str) -> str:
        assert "<conversation_history>" in prompt
        return "The space complexity is O(V^2) regardless of edge density [Document: Graphs.pdf, Page: 4]."

    turn_2 = answer_question(
        question="What is its space complexity?",
        history=history,
        vector_store=mock_store,
        rewrite_callable=mock_rewrite,
        llm_callable=mock_llm_2,
        model="gemini-2.5-pro",
    )
    assert turn_2.model_used == "gemini-2.5-pro"
    assert "O(V^2)" in turn_2.answer
    assert turn_2.citations[0].page_number == 4

def test_model_specific_quota_error_no_silent_switch():
    """6. Model-specific quota error reports target model explicitly without silent replacement."""
    mock_client = MagicMock()
    quota_exc = Exception("429 RESOURCE_EXHAUSTED Quota exceeded for model gemini-2.5-pro")
    mock_client.models.generate_content.side_effect = quota_exc
    mock_sleep = MagicMock()

    with patch.object(settings, "GEMINI_API_KEY", "test_key_123"):
        with pytest.raises(RuntimeError) as exc_info:
            call_gemini(
                prompt="Explain Dijkstra",
                model="gemini-2.5-pro",
                client=mock_client,
                sleep_fn=mock_sleep,
                allow_fallback=False,  # Target model selected: do not silently switch
            )

    err_msg = str(exc_info.value)
    assert "daily quota exceeded for model 'gemini-2.5-pro'" in err_msg.lower()

def test_model_caching_and_refresh():
    """Verify in-memory model caching avoids repetitive external API calls."""
    mock_client = MagicMock()
    m = MagicMock()
    m.name = "models/gemini-2.5-flash"
    m.display_name = "Gemini 2.5 Flash"
    m.description = "Flash model"
    m.supported_generation_methods = ["generateContent"]
    mock_client.models.list.return_value = [m]

    # Force fresh fetch
    res1 = model_service.get_available_models(refresh=True, client=mock_client)
    assert mock_client.models.list.call_count == 1

    # Second call without refresh should use in-memory cache
    res2 = model_service.get_available_models(refresh=False, client=mock_client)
    assert mock_client.models.list.call_count == 1
    assert len(res2.models) == len(res1.models)

    # Clean up cache for subsequent tests
    model_service._cached_models = None

# -----------------------------------------------------------------------------
# 11. Full Code Input & Multiline Snippet Processing Tests
# -----------------------------------------------------------------------------
def test_query_with_javascript_find_maximum_snippet():
    """Verify processing of the exact findMaximum JavaScript function."""
    js_code = """function findMaximum(nums) {
  let max = nums[0];

  for (let i = 1; i < nums.length; i++) {
    if (nums[i] > max) {
      max = nums[i];
    }
  }

  return max;
}"""
    mock_chunks = [
        {
            "text": "Linear scan iterates through array elements to find the maximum in O(n) time.",
            "document_name": "Algorithms.pdf",
            "page_number": 12,
            "similarity": 0.94,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def mock_llm(prompt: str) -> str:
        # Verify the exact code with indentation reached the LLM prompt without corruption
        assert "function findMaximum(nums)" in prompt
        assert "  let max = nums[0];" in prompt
        assert "    if (nums[i] > max)" in prompt
        return "This function finds the maximum element in O(n) time [Document: Algorithms.pdf, Page: 12]."

    response = answer_question(
        question=js_code,
        vector_store=mock_store,
        llm_callable=mock_llm,
        model="gemini-3.5-flash-lite",
    )
    assert not response.insufficient_context
    assert not response.is_error
    assert "O(n) time" in response.answer
    assert response.citations[0].page_number == 12

def test_query_with_python_indentation_preserved():
    """Verify Python code with tabs and 4-space indentation is preserved strictly."""
    py_code = """def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)"""

    mock_chunks = [
        {
            "text": "Quicksort selects a pivot and partitions the elements recursively.",
            "document_name": "Sorting.pdf",
            "page_number": 7,
            "similarity": 0.91,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def mock_llm(prompt: str) -> str:
        assert "    if len(arr) <= 1:" in prompt
        assert "    pivot = arr[len(arr) // 2]" in prompt
        return "Quicksort partitions around a pivot [Document: Sorting.pdf, Page: 7]."

    response = answer_question(
        question=py_code,
        vector_store=mock_store,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert response.citations[0].document_name == "Sorting.pdf"

def test_query_with_large_100_line_code_snippet():
    """Verify backend accepts a large 100-line code snippet without 422 validation failure."""
    lines = [f"    # Line {i}: processing data item {i} in pipeline" for i in range(1, 105)]
    large_code = "def large_pipeline_process():\n" + "\n".join(lines) + "\n    return True\n"
    assert len(large_code.splitlines()) > 100

    with patch("app.services.rag_service.call_gemini") as mock_gemini:
        mock_gemini.return_value = "The pipeline processes items in sequential order."
        response = client.post(
            "/api/tutor/query",
            json={"question": large_code, "model": "gemini-3.5-flash-lite"}
        )
        assert response.status_code == 200
        data = response.json()
        assert not data["is_error"]

def test_query_with_stack_trace_error_log():
    """Verify error logs and stack traces are accepted and processed accurately."""
    stack_trace = """Traceback (most recent call last):
  File "app/main.py", line 42, in process_item
    result = calculate_metrics(data[key])
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyError: 'user_id'
During handling of the above exception, another exception occurred:
ValueError: Failed to parse user profile payload."""

    mock_chunks = [
        {
            "text": "KeyError occurs when trying to access a dictionary key that does not exist.",
            "document_name": "Python_Errors.pdf",
            "page_number": 19,
            "similarity": 0.89,
        }
    ]
    mock_store = MockVectorStore(mock_chunks)

    def mock_llm(prompt: str) -> str:
        assert "KeyError: 'user_id'" in prompt
        return "The KeyError indicates 'user_id' is missing from the dictionary [Document: Python_Errors.pdf, Page: 19]."

    response = answer_question(
        question=stack_trace,
        vector_store=mock_store,
        llm_callable=mock_llm,
    )
    assert not response.insufficient_context
    assert "KeyError" in response.answer
    assert response.citations[0].page_number == 19




