import pytest
import uuid
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db, SessionLocal, engine
from app.db.base import Base
from app.models.conversation import Conversation, Message
from app.schemas.tutor import QueryResponse, Citation
from app.services.conversation_service import generate_conversation_title

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db():
    """Ensure database tables exist and clean up after each test."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.commit()
    finally:
        db.close()


# -----------------------------------------------------------------------------
# 1. Title Generation Unit Tests
# -----------------------------------------------------------------------------
def test_generate_conversation_title():
    assert "IIFE" in generate_conversation_title("What is an IIFE in JavaScript?")
    assert "Binary search" in generate_conversation_title("Can you please explain binary search?")
    assert "Code: calculateTax()" == generate_conversation_title("function calculateTax(income) {\n  return income * 0.2;\n}")
    assert "Code: QuickSort()" == generate_conversation_title("def QuickSort(arr):\n    pass")
    assert "New Conversation" == generate_conversation_title("")


# -----------------------------------------------------------------------------
# 2. Conversation CRUD API Tests
# -----------------------------------------------------------------------------
def test_create_conversation():
    session_id = "test_user_session_1"
    response = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={
            "title": "Algorithms & Complexity",
            "selected_model": "gemini-3.5-flash-lite",
            "document_filter": "DSA_Notes.pdf",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Algorithms & Complexity"
    assert data["session_id"] == session_id
    assert data["selected_model"] == "gemini-3.5-flash-lite"
    assert data["document_filter"] == "DSA_Notes.pdf"
    assert len(data["messages"]) == 0
    assert "id" in data


def test_list_conversations():
    session_id = "test_user_session_list"
    # Create two conversations
    client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "Thread 1"},
    )
    client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "Thread 2"},
    )

    response = client.get("/api/conversations", headers={"X-Session-ID": session_id})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["conversations"]) == 2
    titles = [c["title"] for c in data["conversations"]]
    assert "Thread 1" in titles
    assert "Thread 2" in titles


def test_get_conversation_detail():
    session_id = "test_user_session_detail"
    create_res = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "Detail Test"},
    )
    conv_id = create_res.json()["id"]

    response = client.get(f"/api/conversations/{conv_id}", headers={"X-Session-ID": session_id})
    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == conv_id
    assert detail["title"] == "Detail Test"
    assert isinstance(detail["messages"], list)


def test_update_conversation_rename():
    session_id = "test_user_session_rename"
    create_res = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "Initial Title"},
    )
    conv_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/conversations/{conv_id}",
        headers={"X-Session-ID": session_id},
        json={"title": "Updated Modern Title", "document_filter": "Chapter1.pdf"},
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["title"] == "Updated Modern Title"
    assert updated["document_filter"] == "Chapter1.pdf"

    # Verify retrieval reflects new title
    get_res = client.get(f"/api/conversations/{conv_id}", headers={"X-Session-ID": session_id})
    assert get_res.json()["title"] == "Updated Modern Title"


def test_delete_conversation_cascades_messages():
    session_id = "test_user_session_delete"
    create_res = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "To Delete"},
    )
    conv_id = create_res.json()["id"]

    # Directly insert a message in DB to verify cascade
    db = SessionLocal()
    msg = Message(
        conversation_id=conv_id,
        role="user",
        content="Hello world",
        status="completed",
    )
    db.add(msg)
    db.commit()
    msg_id = msg.id
    db.close()

    # Delete conversation
    del_res = client.delete(f"/api/conversations/{conv_id}", headers={"X-Session-ID": session_id})
    assert del_res.status_code == 200

    # Verify conversation is gone (404)
    get_res = client.get(f"/api/conversations/{conv_id}", headers={"X-Session-ID": session_id})
    assert get_res.status_code == 404

    # Verify message was cascaded and deleted from DB
    db = SessionLocal()
    orphan_msg = db.query(Message).filter(Message.id == msg_id).first()
    assert orphan_msg is None
    db.close()


# -----------------------------------------------------------------------------
# 3. Message Sending & Persistence Tests
# -----------------------------------------------------------------------------
@patch("app.services.conversation_service.answer_question")
def test_send_conversation_message_success(mock_answer):
    mock_answer.return_value = QueryResponse(
        question="What is an IIFE?",
        answer="An IIFE (Immediately Invoked Function Expression) runs immediately after definition. [Document: JS_Course.pdf, Page: 12]",
        citations=[Citation(document_name="JS_Course.pdf", page_number=12, snippet="IIFE runs immediately...")],
        insufficient_context=False,
        is_error=False,
        model_used="gemini-3.5-flash-lite",
    )

    session_id = "test_user_msg_send"
    create_res = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "New Conversation", "selected_model": "gemini-3.5-flash-lite"},
    )
    conv_id = create_res.json()["id"]

    # Send message
    send_res = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers={"X-Session-ID": session_id},
        json={
            "question": "What is an IIFE?",
            "model": "gemini-3.5-flash-lite",
        },
    )
    assert send_res.status_code == 200
    data = send_res.json()

    # Check user message
    user_msg = data["user_message"]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "What is an IIFE?"
    assert user_msg["conversation_id"] == conv_id

    # Check assistant message
    asst_msg = data["assistant_message"]
    assert asst_msg["role"] == "assistant"
    assert "IIFE" in asst_msg["content"]
    assert len(asst_msg["citations"]) == 1
    assert asst_msg["citations"][0]["document_name"] == "JS_Course.pdf"
    assert asst_msg["citations"][0]["page_number"] == 12
    assert asst_msg["model_used"] == "gemini-3.5-flash-lite"

    # Check auto-titling on initial message
    conv_summary = data["conversation"]
    assert conv_summary["title"] != "New Conversation"
    assert "IIFE" in conv_summary["title"]
    assert conv_summary["message_count"] == 2

    # Verify fetching conversation retrieves both messages in chronological order
    get_res = client.get(f"/api/conversations/{conv_id}", headers={"X-Session-ID": session_id})
    assert get_res.status_code == 200
    thread = get_res.json()
    assert len(thread["messages"]) == 2
    assert thread["messages"][0]["role"] == "user"
    assert thread["messages"][1]["role"] == "assistant"


@patch("app.services.conversation_service.answer_question")
def test_conversation_message_order_preserved(mock_answer):
    session_id = "test_user_order"
    create_res = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "Ordering Test"},
    )
    conv_id = create_res.json()["id"]

    mock_answer.side_effect = [
        QueryResponse(
            question="Question 1",
            answer="Answer 1",
            citations=[],
            insufficient_context=False,
            is_error=False,
            model_used="gemini-3.5-flash-lite",
        ),
        QueryResponse(
            question="Question 2",
            answer="Answer 2",
            citations=[],
            insufficient_context=False,
            is_error=False,
            model_used="gemini-3.5-flash-lite",
        ),
    ]

    client.post(
        f"/api/conversations/{conv_id}/messages",
        headers={"X-Session-ID": session_id},
        json={"question": "Question 1"},
    )
    client.post(
        f"/api/conversations/{conv_id}/messages",
        headers={"X-Session-ID": session_id},
        json={"question": "Question 2"},
    )

    get_res = client.get(f"/api/conversations/{conv_id}", headers={"X-Session-ID": session_id})
    messages = get_res.json()["messages"]
    assert len(messages) == 4
    assert messages[0]["content"] == "Question 1"
    assert messages[1]["content"] == "Answer 1"
    assert messages[2]["content"] == "Question 2"
    assert messages[3]["content"] == "Answer 2"


# -----------------------------------------------------------------------------
# 4. Session Isolation Tests
# -----------------------------------------------------------------------------
def test_conversation_session_isolation():
    session_a = "user_alpha_session"
    session_b = "user_beta_session"

    res_a = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_a},
        json={"title": "Alpha Private Thread"},
    )
    conv_a_id = res_a.json()["id"]

    res_b = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_b},
        json={"title": "Beta Private Thread"},
    )
    conv_b_id = res_b.json()["id"]

    # Alpha should only list Alpha's conversation
    list_a = client.get("/api/conversations", headers={"X-Session-ID": session_a}).json()
    assert list_a["total"] == 1
    assert list_a["conversations"][0]["id"] == conv_a_id

    # Beta should only list Beta's conversation
    list_b = client.get("/api/conversations", headers={"X-Session-ID": session_b}).json()
    assert list_b["total"] == 1
    assert list_b["conversations"][0]["id"] == conv_b_id

    # Alpha cannot access Beta's conversation directly (returns 404)
    access_b = client.get(f"/api/conversations/{conv_b_id}", headers={"X-Session-ID": session_a})
    assert access_b.status_code == 404

    # Alpha cannot delete Beta's conversation
    delete_b = client.delete(f"/api/conversations/{conv_b_id}", headers={"X-Session-ID": session_a})
    assert delete_b.status_code == 404


# -----------------------------------------------------------------------------
# 5. Error & Edge Case Handling Tests
# -----------------------------------------------------------------------------
def test_get_nonexistent_conversation_returns_404():
    fake_id = str(uuid.uuid4())
    res = client.get(f"/api/conversations/{fake_id}", headers={"X-Session-ID": "session_err"})
    assert res.status_code == 404


def test_send_message_to_nonexistent_conversation_returns_404():
    fake_id = str(uuid.uuid4())
    session_id = "session_err"
    res = client.post(
        f"/api/conversations/{fake_id}/messages",
        headers={"X-Session-ID": session_id},
        json={"question": "Does this exist?"},
    )
    assert res.status_code == 404


def test_send_empty_message_returns_422():
    session_id = "test_empty_msg"
    create_res = client.post(
        "/api/conversations",
        headers={"X-Session-ID": session_id},
        json={"title": "Empty Msg Test"},
    )
    conv_id = create_res.json()["id"]

    res = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers={"X-Session-ID": session_id},
        json={"question": "   "},
    )
    assert res.status_code == 422
