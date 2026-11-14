"""
Unit and integration tests for CodePilot RAG pgvector migration and embedding provider abstraction.

Covers:
- Critical Issue 1: Gemini Embedding 2 compatibility:
  * No unsupported task_type in EmbedContentConfig
  * Retrieval prompt instructions ('title: ... | text: ...', 'task: search result | query: ...')
  * Separate distinct embeddings per input chunk (1:1 mapping)
  * Dimension truncation via output_dimensionality
  * SDK response parsing and validation
- Critical Issue 2: Dimension consistency:
  * Setting validation rejecting unsupported dimensions for pgvector
  * PgVectorStoreService dimension validation and mismatch rejection
- Critical Issue 3: Offline test execution (mocked Gemini calls, SQLite test db)
"""

import math
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings, Settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_chunk import DocumentChunkModel, VectorType, PGVECTOR_CANONICAL_DIMENSION
from app.schemas.tutor import DocumentChunk
from app.services.embedding_provider import (
    EmbeddingProvider,
    LocalSentenceTransformerProvider,
    GeminiEmbeddingProvider,
    get_embedding_provider,
    reset_embedding_provider,
)
from app.services.vector_store import (
    VectorStoreService,
    ChromaVectorStoreService,
    PgVectorStoreService,
    _cosine_distance,
)
from app.services.rag_service import answer_question_with_trace


class MockDeterministicEmbeddingProvider(EmbeddingProvider):
    """Deterministic test embedding provider returning predictable unit vectors."""

    def __init__(self, dim: int = 4):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_texts(self, texts: list[str], titles: list[str] | None = None) -> list[list[float]]:
        results = []
        for text in texts:
            if "python" in text.lower():
                vec = [1.0, 0.0, 0.0, 0.0]
            elif "javascript" in text.lower():
                vec = [0.0, 1.0, 0.0, 0.0]
            elif "database" in text.lower():
                vec = [0.0, 0.0, 1.0, 0.0]
            else:
                vec = [0.5, 0.5, 0.5, 0.5]
            results.append(vec)
        return results

    def embed_query(self, query: str) -> list[float]:
        q = query.lower()
        if "python" in q:
            return [1.0, 0.0, 0.0, 0.0]
        elif "javascript" in q:
            return [0.0, 1.0, 0.0, 0.0]
        elif "database" in q:
            return [0.0, 0.0, 1.0, 0.0]
        return [0.5, 0.5, 0.5, 0.5]


# ===========================================================================
# 1. Critical Issue 1: Gemini Embedding 2 Compatibility Tests
# ===========================================================================

def test_cosine_distance_math():
    """Verify cosine distance helper correctly handles orthogonal, identical, and zero vectors."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert _cosine_distance(v1, v2) == pytest.approx(0.0, abs=1e-6)

    v3 = [0.0, 1.0, 0.0]
    assert _cosine_distance(v1, v3) == pytest.approx(1.0, abs=1e-6)

    # Zero vector safety
    v_zero = [0.0, 0.0, 0.0]
    assert _cosine_distance(v1, v_zero) == 1.0


def test_gemini_embedding_provider_initialization():
    """Verify GeminiEmbeddingProvider initializes with configurable model and 768 dimensions."""
    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-2",
        dimension=768,
        client=MagicMock(),
    )
    assert provider.model == "gemini-embedding-2"
    assert provider.dimension == 768


def test_gemini_embedding_provider_unsupported_dimension_rejected():
    """Verify provider rejects unsupported dimensions during initialization."""
    with pytest.raises(ValueError, match="Unsupported embedding dimension"):
        GeminiEmbeddingProvider(
            model="gemini-embedding-2",
            dimension=384,  # Not supported by gemini-embedding-2 MRL
            client=MagicMock(),
        )


def test_gemini_embedding_provider_embed_texts_documented_format():
    """
    CRITICAL: Verify GeminiEmbeddingProvider does NOT send task_type,
    formats documents as 'title: ... | text: ...', and receives separate embeddings.
    """
    mock_client = MagicMock()
    mock_item_1 = MagicMock()
    mock_item_1.values = [0.1] * 768
    mock_item_2 = MagicMock()
    mock_item_2.values = [0.2] * 768

    mock_response = MagicMock()
    mock_response.embeddings = [mock_item_1, mock_item_2]
    mock_client.models.embed_content.return_value = mock_response

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-2",
        dimension=768,
        client=mock_client,
    )

    texts = ["First chunk of text", "Second chunk of text"]
    titles = ["cs101.pdf", "cs101.pdf"]
    embeddings = provider.embed_texts(texts, titles=titles)

    assert len(embeddings) == 2
    assert embeddings[0] == [0.1] * 768
    assert embeddings[1] == [0.2] * 768

    mock_client.models.embed_content.assert_called_once()
    call_kwargs = mock_client.models.embed_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-embedding-2"
    # Document instruction format
    assert call_kwargs["contents"] == [
        "title: cs101.pdf | text: First chunk of text",
        "title: cs101.pdf | text: Second chunk of text",
    ]
    # No task_type parameter sent
    assert not hasattr(call_kwargs["config"], "task_type") or call_kwargs["config"].task_type is None
    # output_dimensionality configured
    assert call_kwargs["config"].output_dimensionality == 768


def test_gemini_embedding_provider_embed_query_documented_format():
    """
    CRITICAL: Verify GeminiEmbeddingProvider formats queries as
    'task: search result | query: ...' and does NOT send task_type.
    """
    mock_client = MagicMock()
    mock_item = MagicMock()
    mock_item.values = [0.3] * 768

    mock_response = MagicMock()
    mock_response.embeddings = [mock_item]
    mock_client.models.embed_content.return_value = mock_response

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-2",
        dimension=768,
        client=mock_client,
    )

    query = "What is a closure in Python?"
    embedding = provider.embed_query(query)

    assert embedding == [0.3] * 768
    mock_client.models.embed_content.assert_called_once()
    call_kwargs = mock_client.models.embed_content.call_args.kwargs
    assert call_kwargs["contents"] == ["task: search result | query: What is a closure in Python?"]
    assert not hasattr(call_kwargs["config"], "task_type") or call_kwargs["config"].task_type is None
    assert call_kwargs["config"].output_dimensionality == 768


def test_gemini_embedding_provider_enforces_separate_embeddings():
    """Verify that multiple text inputs must receive separate embeddings (1:1 mapping)."""
    mock_client = MagicMock()
    mock_single_item = MagicMock()
    mock_single_item.values = [0.5] * 768

    # Faulty response returning 1 aggregated embedding for 2 input chunks
    mock_response = MagicMock()
    mock_response.embeddings = [mock_single_item]
    mock_client.models.embed_content.return_value = mock_response

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-2",
        dimension=768,
        client=mock_client,
    )

    with pytest.raises(RuntimeError, match="expected separate embeddings"):
        provider.embed_texts(["Chunk 1", "Chunk 2"])


def test_gemini_embedding_provider_dimension_mismatch_raised():
    """Verify that returned embeddings with unexpected dimensions are rejected."""
    mock_client = MagicMock()
    mock_item = MagicMock()
    mock_item.values = [0.1] * 384  # Mismatch: 384 instead of 768

    mock_response = MagicMock()
    mock_response.embeddings = [mock_item]
    mock_client.models.embed_content.return_value = mock_response

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-2",
        dimension=768,
        client=mock_client,
    )

    with pytest.raises(ValueError, match="does not match expected 768"):
        provider.embed_query("test query")


def test_gemini_embedding_provider_transient_retry():
    """Verify provider retries on transient rate-limit errors."""
    mock_client = MagicMock()
    sleep_calls = []

    rate_limit_error = Exception("429 RESOURCE_EXHAUSTED: Rate limit exceeded")
    mock_item = MagicMock()
    mock_item.values = [0.1] * 768
    mock_success = MagicMock()
    mock_success.embeddings = [mock_item]

    mock_client.models.embed_content.side_effect = [rate_limit_error, mock_success]

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-2",
        dimension=768,
        client=mock_client,
        max_retries=2,
        sleep_fn=lambda s: sleep_calls.append(s),
    )

    result = provider.embed_query("test query")
    assert result == [0.1] * 768
    assert mock_client.models.embed_content.call_count == 2
    assert len(sleep_calls) == 1


# ===========================================================================
# 2. Critical Issue 2: Embedding Dimension Consistency & Rejection Tests
# ===========================================================================

def test_settings_pgvector_dimension_validation():
    """Verify Settings rejects unsupported EMBEDDING_DIMENSION when VECTOR_STORE_BACKEND=pgvector."""
    # 768 is canonical and must succeed
    valid_settings = Settings(
        VECTOR_STORE_BACKEND="pgvector",
        EMBEDDING_DIMENSION=768,
    )
    assert valid_settings.EMBEDDING_DIMENSION == 768

    # 384 must be rejected for pgvector
    with pytest.raises(ValueError, match="Unsupported EMBEDDING_DIMENSION=384 for pgvector backend"):
        Settings(
            VECTOR_STORE_BACKEND="pgvector",
            EMBEDDING_DIMENSION=384,
        )


def test_pgvector_store_dimension_mismatch_rejection():
    """Verify PgVectorStoreService rejects embedding provider with mismatched dimension."""
    # Vector store expects 768, but provider produces 384 (e.g. SentenceTransformers)
    mismatched_provider = MagicMock(spec=EmbeddingProvider)
    mismatched_provider.dimension = 384

    store = PgVectorStoreService(
        embedding_provider=mismatched_provider,
        expected_dimension=768,
    )

    chunks = [
        DocumentChunk(
            id="c1",
            document_name="test.pdf",
            page_number=1,
            chunk_index=0,
            text="sample text",
        )
    ]

    with pytest.raises(ValueError, match="does not match pgvector store dimension"):
        store.add_document_chunks(
            chunks=chunks,
            user_id="user_test",
            document_id="doc_test",
        )


def test_pgvector_store_query_dimension_mismatch_rejection():
    """Verify PgVectorStoreService rejects query embedding with mismatched dimension."""
    mock_provider = MagicMock(spec=EmbeddingProvider)
    mock_provider.dimension = 768
    mock_provider.embed_query.return_value = [0.1] * 384  # Wrong dimension returned

    store = PgVectorStoreService(
        embedding_provider=mock_provider,
        expected_dimension=768,
    )

    with pytest.raises(ValueError, match="Query embedding dimension 384 does not match"):
        store.similarity_search(query="test", user_id="user_test")


# ===========================================================================
# 3. PgVectorStoreService Storage, Similarity, and Isolation Tests
# ===========================================================================

@pytest.fixture
def mock_pgvector_store():
    """Provide a dedicated PgVectorStoreService wired with a deterministic mock embedder (4 dims)."""
    embedder = MockDeterministicEmbeddingProvider(dim=4)
    store = PgVectorStoreService(embedding_provider=embedder, expected_dimension=4)
    return store


def test_pgvector_store_add_and_search_basic(mock_pgvector_store):
    """Verify document chunk addition and similarity search in PgVectorStoreService."""
    user_id = "user_alpha"
    doc_id = "doc_alpha_1"
    chunks = [
        DocumentChunk(
            id="chunk_1",
            document_name="python_basics.pdf",
            page_number=1,
            chunk_index=0,
            text="Python is a high-level dynamically typed programming language.",
        ),
        DocumentChunk(
            id="chunk_2",
            document_name="python_basics.pdf",
            page_number=2,
            chunk_index=1,
            text="JavaScript runs in the browser and handles interactive web DOM.",
        ),
    ]

    mock_pgvector_store.add_document_chunks(
        chunks=chunks,
        user_id=user_id,
        document_id=doc_id,
        file_size_bytes=1024,
    )

    results = mock_pgvector_store.similarity_search(
        query="Tell me about Python language",
        user_id=user_id,
        top_k=2,
    )

    assert len(results) == 2
    top = results[0]
    assert "Python is a high-level" in top["text"]
    assert top["document_name"] == "python_basics.pdf"
    assert top["document_id"] == doc_id
    assert top["user_id"] == user_id
    assert top["page_number"] == 1
    assert top["similarity"] >= 0.99


def test_pgvector_store_strict_tenant_isolation(mock_pgvector_store):
    """
    STRICT SECURITY RULE:
    Verify User A can never retrieve User B's document chunks even with an exact matching query.
    """
    user_a = "user_victim_a"
    user_b = "user_attacker_b"

    chunks_a = [
        DocumentChunk(
            id="sec_chunk_a",
            document_name="confidential_python.pdf",
            page_number=1,
            chunk_index=0,
            text="Proprietary Python algorithm for User A secret analysis.",
        )
    ]
    chunks_b = [
        DocumentChunk(
            id="sec_chunk_b",
            document_name="public_database.pdf",
            page_number=1,
            chunk_index=0,
            text="Relational database concepts and SQL queries for User B.",
        )
    ]

    mock_pgvector_store.add_document_chunks(
        chunks=chunks_a,
        user_id=user_a,
        document_id="doc_a_100",
    )
    mock_pgvector_store.add_document_chunks(
        chunks=chunks_b,
        user_id=user_b,
        document_id="doc_b_200",
    )

    # User B searches specifically for User A's topic: "Python algorithm"
    results_for_b = mock_pgvector_store.similarity_search(
        query="Python algorithm secret",
        user_id=user_b,
        top_k=5,
    )

    # User B should NOT see User A's confidential document
    for r in results_for_b:
        assert r["user_id"] == user_b
        assert r["document_name"] != "confidential_python.pdf"
        assert "secret analysis" not in r["text"]

    # User A searches for Python and finds their own document
    results_for_a = mock_pgvector_store.similarity_search(
        query="Python algorithm secret",
        user_id=user_a,
        top_k=5,
    )
    assert len(results_for_a) == 1
    assert results_for_a[0]["user_id"] == user_a
    assert results_for_a[0]["document_name"] == "confidential_python.pdf"


def test_pgvector_store_document_filter(mock_pgvector_store):
    """Verify document_filter restricts search results strictly to the targeted document."""
    user_id = "user_filter_test"
    mock_pgvector_store.add_document_chunks(
        chunks=[
            DocumentChunk(
                id="doc1_chunk0",
                document_name="python_course.pdf",
                page_number=1,
                chunk_index=0,
                text="Python functions and recursion.",
            )
        ],
        user_id=user_id,
        document_id="doc_filter_1",
    )
    mock_pgvector_store.add_document_chunks(
        chunks=[
            DocumentChunk(
                id="doc2_chunk0",
                document_name="advanced_python.pdf",
                page_number=1,
                chunk_index=0,
                text="Python metaclasses and decorators.",
            )
        ],
        user_id=user_id,
        document_id="doc_filter_2",
    )

    results = mock_pgvector_store.similarity_search(
        query="Python",
        user_id=user_id,
        top_k=5,
        document_filter="python_course.pdf",
    )

    assert len(results) == 1
    assert results[0]["document_name"] == "python_course.pdf"
    assert "recursion" in results[0]["text"]


def test_pgvector_store_unauthenticated_query_raises(mock_pgvector_store):
    """Verify similarity search rejects unauthenticated or empty user_id."""
    with pytest.raises(ValueError, match="user_id is strictly required"):
        mock_pgvector_store.similarity_search(query="hello", user_id="")

    with pytest.raises(ValueError, match="user_id is strictly required"):
        mock_pgvector_store.similarity_search(query="hello", user_id="   ")


def test_pgvector_store_list_and_delete_documents(mock_pgvector_store):
    """Verify list_documents, delete_document, and clear_user_documents."""
    user_id = "user_mgmt_test"
    mock_pgvector_store.add_document_chunks(
        chunks=[
            DocumentChunk(
                id="mgmt_c1",
                document_name="delete_me.pdf",
                page_number=1,
                chunk_index=0,
                text="Temporary document chunk 1.",
            ),
            DocumentChunk(
                id="mgmt_c2",
                document_name="delete_me.pdf",
                page_number=2,
                chunk_index=1,
                text="Temporary document chunk 2.",
            ),
        ],
        user_id=user_id,
        document_id="doc_delete_1",
        file_size_bytes=2048,
    )
    mock_pgvector_store.add_document_chunks(
        chunks=[
            DocumentChunk(
                id="mgmt_c3",
                document_name="keep_me.pdf",
                page_number=1,
                chunk_index=0,
                text="Keeper document chunk 1.",
            )
        ],
        user_id=user_id,
        document_id="doc_keep_2",
        file_size_bytes=4096,
    )

    docs = mock_pgvector_store.list_documents(user_id=user_id)
    assert len(docs) == 2
    names = {d.document_name for d in docs}
    assert "delete_me.pdf" in names
    assert "keep_me.pdf" in names

    deleted = mock_pgvector_store.delete_document(user_id=user_id, document_identifier="delete_me.pdf")
    assert deleted is True

    docs_after = mock_pgvector_store.list_documents(user_id=user_id)
    assert len(docs_after) == 1
    assert docs_after[0].document_name == "keep_me.pdf"

    cleared_count = mock_pgvector_store.clear_user_documents(user_id=user_id)
    assert cleared_count == 1
    assert mock_pgvector_store.list_documents(user_id=user_id) == []


# ===========================================================================
# 4. Vector Store Backend Selection & Factory Tests
# ===========================================================================

def test_vector_store_backend_switch_to_pgvector(monkeypatch):
    """Verify VectorStoreService.get_instance() dispatches to PgVectorStoreService when configured."""
    PgVectorStoreService.reset_instance()
    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "pgvector")

    instance = VectorStoreService.get_instance()
    assert isinstance(instance, PgVectorStoreService)

    PgVectorStoreService.reset_instance()


def test_vector_store_backend_switch_to_chroma(monkeypatch):
    """Verify VectorStoreService.get_instance() dispatches to ChromaVectorStoreService by default."""
    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "chroma")

    instance = VectorStoreService.get_instance()
    assert isinstance(instance, ChromaVectorStoreService)


# ===========================================================================
# 5. RAG Service End-to-End Pipeline with pgvector
# ===========================================================================

def test_answer_question_with_pgvector_store(mock_pgvector_store):
    """Verify answer_question_with_trace retrieves from PgVectorStoreService and formats citations."""
    user_id = "user_rag_e2e"
    doc_id = "doc_rag_1"

    mock_pgvector_store.add_document_chunks(
        chunks=[
            DocumentChunk(
                id="rag_chunk_py",
                document_name="python_course.pdf",
                page_number=7,
                chunk_index=0,
                text="In Python, list comprehensions provide a concise way to create lists from sequences.",
            )
        ],
        user_id=user_id,
        document_id=doc_id,
    )

    mock_llm_callable = MagicMock(return_value="List comprehensions allow concise list creation [Document: python_course.pdf, Page: 7].")

    response, trace = answer_question_with_trace(
        question="How do Python list comprehensions work?",
        user_id=user_id,
        vector_store=mock_pgvector_store,
        llm_callable=mock_llm_callable,
    )

    assert response.is_error is False
    assert len(response.citations) >= 1
    assert response.citations[0].document_name == "python_course.pdf"
    assert response.citations[0].page_number == 7
    assert "concise way to create lists" in response.citations[0].snippet
    assert trace.max_similarity >= 0.9
