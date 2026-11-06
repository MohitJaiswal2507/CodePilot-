import io
import time
import uuid
import pytest
import jwt
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ed25519
from pypdf import PdfWriter

from app.main import app
from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.models.document import Document
from app.models.conversation import Conversation, Message
from app.core.config import settings
from app.services.vector_store import VectorStoreService

client = TestClient(app)

# Signing key for test JWTs
ed_private_key = ed25519.Ed25519PrivateKey.generate()
ed_public_key = ed_private_key.public_key()


def generate_test_jwt(user_id: str, email: str = "test@example.com") -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now - 10,
        "exp": now + 3600,
    }
    if settings.NEON_AUTH_ISSUER:
        payload["iss"] = settings.NEON_AUTH_ISSUER
    if settings.NEON_AUTH_AUDIENCE:
        payload["aud"] = settings.NEON_AUTH_AUDIENCE
    return jwt.encode(payload, ed_private_key, algorithm="EdDSA")


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


@pytest.fixture(autouse=True)
def mock_jwks_global():
    """Ensure all JWT verifications in these tests use the test EdDSA public key."""
    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    with patch("app.core.auth.get_jwks_client", return_value=mock_client), \
         patch.object(settings, "ENVIRONMENT", "production"):
        yield


@pytest.fixture
def clean_test_users_data():
    """Clean up test documents and conversations before and after test."""
    test_user_ids = ["user_mohit_jaiswal_1", "user_admin2_2", "user_admin_3"]
    db = SessionLocal()
    vs = VectorStoreService.get_instance()
    try:
        for uid in test_user_ids:
            db.query(Document).filter(Document.owner_user_id == uid).delete()
            db.query(Conversation).filter(Conversation.user_id == uid).delete()
            vs.clear_user_documents(uid)
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        for uid in test_user_ids:
            db.query(Document).filter(Document.owner_user_id == uid).delete()
            db.query(Conversation).filter(Conversation.user_id == uid).delete()
            vs.clear_user_documents(uid)
        db.commit()
    finally:
        db.close()


def test_three_account_multi_user_rag_isolation(clean_test_users_data):
    """
    Comprehensive Multi-Account RAG Data Isolation Security Test:
    Verify strict isolation between 3 independent accounts across:
    - Document uploads and PostgreSQL ownership
    - ChromaDB vector chunk isolation
    - Listing scoping
    - Similarity search and RAG retrieval scoping
    - Document deletion ownership enforcement
    - Conversation isolation
    - Quarantined legacy chunk shielding
    """
    user_a = "user_mohit_jaiswal_1"
    user_b = "user_admin2_2"
    user_c = "user_admin_3"

    token_a = generate_test_jwt(user_a, "mohit@codepilot.ai")
    token_b = generate_test_jwt(user_b, "admin2@codepilot.ai")
    token_c = generate_test_jwt(user_c, "admin@codepilot.ai")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    headers_c = {"Authorization": f"Bearer {token_c}"}

    # -------------------------------------------------------------------------
    # 1. User A uploads PDF A (Algorithms)
    # -------------------------------------------------------------------------
    pdf_bytes_a = _create_sample_pdf("Binary search tree has O(log n) average time complexity.")
    res_upload_a = client.post(
        "/api/tutor/upload",
        headers=headers_a,
        files={"file": ("algorithms_lecture_a.pdf", io.BytesIO(pdf_bytes_a), "application/pdf")},
    )
    assert res_upload_a.status_code == 201
    doc_a_id = res_upload_a.json()["document"]["id"]
    assert doc_a_id is not None
    assert res_upload_a.json()["document"]["owner_user_id"] == user_a

    # -------------------------------------------------------------------------
    # 2. User B uploads PDF B (Databases)
    # -------------------------------------------------------------------------
    pdf_bytes_b = _create_sample_pdf("ACID transactions guarantee atomicity, consistency, isolation, durability.")
    res_upload_b = client.post(
        "/api/tutor/upload",
        headers=headers_b,
        files={"file": ("database_systems_b.pdf", io.BytesIO(pdf_bytes_b), "application/pdf")},
    )
    assert res_upload_b.status_code == 201
    doc_b_id = res_upload_b.json()["document"]["id"]
    assert res_upload_b.json()["document"]["owner_user_id"] == user_b

    # -------------------------------------------------------------------------
    # 3. User C uploads PDF C (Networks)
    # -------------------------------------------------------------------------
    pdf_bytes_c = _create_sample_pdf("TCP provides reliable, ordered and error-checked delivery of byte streams.")
    res_upload_c = client.post(
        "/api/tutor/upload",
        headers=headers_c,
        files={"file": ("computer_networks_c.pdf", io.BytesIO(pdf_bytes_c), "application/pdf")},
    )
    assert res_upload_c.status_code == 201
    doc_c_id = res_upload_c.json()["document"]["id"]
    assert res_upload_c.json()["document"]["owner_user_id"] == user_c

    # -------------------------------------------------------------------------
    # 4. Strict Document Listing Isolation
    # -------------------------------------------------------------------------
    # User A listing
    list_a = client.get("/api/tutor/documents", headers=headers_a)
    assert list_a.status_code == 200
    docs_a = list_a.json()["documents"]
    assert len(docs_a) == 1
    assert docs_a[0]["document_name"] == "algorithms_lecture_a.pdf"
    assert docs_a[0]["owner_user_id"] == user_a

    # User B listing
    list_b = client.get("/api/tutor/documents", headers=headers_b)
    assert list_b.status_code == 200
    docs_b = list_b.json()["documents"]
    assert len(docs_b) == 1
    assert docs_b[0]["document_name"] == "database_systems_b.pdf"
    assert docs_b[0]["owner_user_id"] == user_b

    # User C listing
    list_c = client.get("/api/tutor/documents", headers=headers_c)
    assert list_c.status_code == 200
    docs_c = list_c.json()["documents"]
    assert len(docs_c) == 1
    assert docs_c[0]["document_name"] == "computer_networks_c.pdf"
    assert docs_c[0]["owner_user_id"] == user_c

    # -------------------------------------------------------------------------
    # 5. ChromaDB Vector Chunk Ownership Isolation
    # -------------------------------------------------------------------------
    vs = VectorStoreService.get_instance()
    # Direct vector search for User B asking about User A's algorithms
    chunks_b = vs.similarity_search("binary search tree", user_id=user_b)
    # User B has only database document indexed, so zero algorithm chunks can ever be returned
    assert all(c["document_name"] != "algorithms_lecture_a.pdf" for c in chunks_b)
    assert all(c["user_id"] == user_b for c in chunks_b)

    # Direct vector search for User A asking about algorithms
    chunks_a = vs.similarity_search("binary search tree", user_id=user_a)
    assert all(c["user_id"] == user_a for c in chunks_a)
    assert all(c["document_name"] != "database_systems_b.pdf" for c in chunks_a)

    # -------------------------------------------------------------------------
    # 6. RAG Query Isolation (User B cannot retrieve User A's documents)
    # -------------------------------------------------------------------------
    query_b = client.post(
        "/api/tutor/query",
        headers=headers_b,
        json={"question": "What is the complexity of binary search tree?", "document_filter": "algorithms_lecture_a.pdf"},
    )
    assert query_b.status_code == 200
    res_b_json = query_b.json()
    # User B cannot retrieve User A's document chunks
    assert res_b_json["insufficient_context"] is True
    assert len(res_b_json["citations"]) == 0

    # -------------------------------------------------------------------------
    # 7. Cross-User Document Deletion Rejection
    # User B tries to delete User A's document (by name or by ID)
    # -------------------------------------------------------------------------
    del_attempt_1 = client.delete(f"/api/tutor/documents/algorithms_lecture_a.pdf", headers=headers_b)
    assert del_attempt_1.status_code == 404
    assert "not found in your learning materials" in del_attempt_1.json()["detail"]

    del_attempt_2 = client.delete(f"/api/tutor/documents/{doc_a_id}", headers=headers_b)
    assert del_attempt_2.status_code == 404

    # Verify User A's document is still intact
    list_a_after = client.get("/api/tutor/documents", headers=headers_a)
    assert len(list_a_after.json()["documents"]) == 1
    assert list_a_after.json()["documents"][0]["id"] == doc_a_id

    # -------------------------------------------------------------------------
    # 8. User ID Tampering in Headers / Body Rejection
    # Attacker passes forged user_id parameter or header
    # -------------------------------------------------------------------------
    fake_header = {"Authorization": f"Bearer {token_b}", "X-User-ID": user_a, "owner_user_id": user_a}
    list_tampered = client.get("/api/tutor/documents", headers=fake_header)
    assert list_tampered.status_code == 200
    # Must STILL return User B's documents, ignoring the forged user_a header!
    assert list_tampered.json()["documents"][0]["owner_user_id"] == user_b

    # -------------------------------------------------------------------------
    # 9. Cross-User Conversation Access Rejection
    # -------------------------------------------------------------------------
    create_conv_a = client.post("/api/conversations", headers=headers_a, json={"title": "User A Private Thread"})
    assert create_conv_a.status_code == 201
    conv_a_id = create_conv_a.json()["id"]

    # User B tries to access User A's conversation
    conv_b_attempt = client.get(f"/api/conversations/{conv_a_id}", headers=headers_b)
    assert conv_b_attempt.status_code == 404

    # -------------------------------------------------------------------------
    # 10. Missing Authentication Rejection
    # -------------------------------------------------------------------------
    no_auth_res = client.get("/api/tutor/documents")
    assert no_auth_res.status_code == 401

    # -------------------------------------------------------------------------
    # 11. Legacy Quarantined Data Shielding
    # Quarantined legacy chunks are completely unreachable by User A, B, or C
    # -------------------------------------------------------------------------
    for token, headers in [(token_a, headers_a), (token_b, headers_b), (token_c, headers_c)]:
        docs_res = client.get("/api/tutor/documents", headers=headers)
        doc_names = [d["document_name"] for d in docs_res.json()["documents"]]
        assert "DS_Lecture-Week-14.pdf" not in doc_names
        assert "DS_Lecture-Week-11.pdf" not in doc_names

    # -------------------------------------------------------------------------
    # 12. Scoped Workspace Clearing (User B clears only their own documents)
    # -------------------------------------------------------------------------
    clear_b = client.delete("/api/tutor/documents", headers=headers_b)
    assert clear_b.status_code == 200

    # User B now has 0 documents
    list_b_cleared = client.get("/api/tutor/documents", headers=headers_b)
    assert len(list_b_cleared.json()["documents"]) == 0

    # User A and User C documents are completely unaffected
    list_a_intact = client.get("/api/tutor/documents", headers=headers_a)
    assert len(list_a_intact.json()["documents"]) == 1
    assert list_a_intact.json()["documents"][0]["id"] == doc_a_id

    list_c_intact = client.get("/api/tutor/documents", headers=headers_c)
    assert len(list_c_intact.json()["documents"]) == 1
    assert list_c_intact.json()["documents"][0]["id"] == doc_c_id
