import pytest
import time
import uuid
import jwt
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives import serialization

from app.main import app
from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.models.conversation import Conversation, Message
from app.core.config import settings

client = TestClient(app)

# Generate test Ed25519 signing keys
ed_private_key = ed25519.Ed25519PrivateKey.generate()
ed_public_key = ed_private_key.public_key()

# Generate test RSA signing keys
rsa_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
rsa_public_key = rsa_private_key.public_key()


def generate_test_jwt(
    user_id: str,
    email: str = "test@example.com",
    expired: bool = False,
    issuer: str = None,
    audience: str = None,
    wrong_key: bool = False,
    alg: str = "EdDSA",
) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now - 100,
        "exp": (now - 300) if expired else (now + 3600),
    }
    effective_iss = issuer if issuer is not None else settings.NEON_AUTH_ISSUER
    if effective_iss:
        payload["iss"] = effective_iss

    effective_aud = audience if audience is not None else settings.NEON_AUTH_AUDIENCE
    if effective_aud:
        payload["aud"] = effective_aud

    if alg == "EdDSA":
        key = ed25519.Ed25519PrivateKey.generate() if wrong_key else ed_private_key
        return jwt.encode(payload, key, algorithm="EdDSA")
    elif alg == "RS256":
        key = rsa.generate_private_key(65537, 2048) if wrong_key else rsa_private_key
        return jwt.encode(payload, key, algorithm="RS256")
    else:
        raise ValueError(f"Unsupported test alg {alg}")


@pytest.fixture
def clean_database():
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
# 1. JWT Verification & Validation Tests
# -----------------------------------------------------------------------------
def test_missing_auth_header_returns_401():
    # Temporarily set ENVIRONMENT="production" to ensure strict auth enforcement
    with patch.object(settings, "ENVIRONMENT", "production"):
        res = client.get("/api/conversations")
        assert res.status_code == 401
        assert "Authentication required" in res.json()["detail"]


def test_malformed_auth_header_returns_401():
    with patch.object(settings, "ENVIRONMENT", "production"):
        res = client.get(
            "/api/conversations",
            headers={"Authorization": "NotABearerToken"}
        )
        assert res.status_code == 401


@patch("app.core.auth.get_jwks_client")
def test_valid_eddsa_jwt_authenticates_user(mock_jwks):
    user_id = "user_neon_abc123"
    token = generate_test_jwt(user_id=user_id, email="alice@codepilot.ai", alg="EdDSA")

    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key
    mock_jwks.return_value = mock_client

    with patch.object(settings, "ENVIRONMENT", "production"):
        res = client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        assert res.json()["total"] == 0


@patch("app.core.auth.get_jwks_client")
def test_expired_jwt_rejected_with_401(mock_jwks):
    user_id = "user_expired_123"
    token = generate_test_jwt(user_id=user_id, expired=True, alg="EdDSA")

    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key
    mock_jwks.return_value = mock_client

    with patch.object(settings, "ENVIRONMENT", "production"):
        res = client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401
        assert "expired" in res.json()["detail"].lower()


@patch("app.core.auth.get_jwks_client")
def test_invalid_signature_rejected_with_401(mock_jwks):
    user_id = "user_tampered_123"
    # Token signed by an unknown key
    token = generate_test_jwt(user_id=user_id, wrong_key=True, alg="EdDSA")

    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key
    mock_jwks.return_value = mock_client

    with patch.object(settings, "ENVIRONMENT", "production"):
        res = client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401
        assert "signature" in res.json()["detail"].lower()


@patch("app.core.auth.get_jwks_client")
def test_invalid_issuer_rejected_with_401(mock_jwks):
    user_id = "user_issuer_test"
    token = generate_test_jwt(user_id=user_id, issuer="https://malicious-issuer.com", alg="EdDSA")

    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key
    mock_jwks.return_value = mock_client

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "NEON_AUTH_ISSUER", "https://official.neonauth.com"):
        res = client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401
        assert "issuer" in res.json()["detail"].lower()


# -----------------------------------------------------------------------------
# 2. Multi-Tenant User Isolation & IDOR Protection Tests
# -----------------------------------------------------------------------------
@patch("app.core.auth.get_jwks_client")
def test_user_owned_conversations_strict_isolation(mock_jwks):
    user_a = "user_alpha_uuid"
    user_b = "user_beta_uuid"

    token_a = generate_test_jwt(user_id=user_a, email="alpha@codepilot.ai", alg="EdDSA")
    token_b = generate_test_jwt(user_id=user_b, email="beta@codepilot.ai", alg="EdDSA")

    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key
    mock_jwks.return_value = mock_client

    with patch.object(settings, "ENVIRONMENT", "production"):
        # User A creates a conversation
        create_res_a = client.post(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"title": "Alpha Private Thread"},
        )
        assert create_res_a.status_code == 201
        conv_a_id = create_res_a.json()["id"]
        assert create_res_a.json()["user_id"] == user_a

        # User B creates a conversation
        create_res_b = client.post(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token_b}"},
            json={"title": "Beta Private Thread"},
        )
        assert create_res_b.status_code == 201
        conv_b_id = create_res_b.json()["id"]
        assert create_res_b.json()["user_id"] == user_b

        # 1. Listing isolation: User A sees only A's threads; User B sees only B's
        list_a = client.get("/api/conversations", headers={"Authorization": f"Bearer {token_a}"}).json()
        assert list_a["total"] == 1
        assert list_a["conversations"][0]["id"] == conv_a_id

        list_b = client.get("/api/conversations", headers={"Authorization": f"Bearer {token_b}"}).json()
        assert list_b["total"] == 1
        assert list_b["conversations"][0]["id"] == conv_b_id

        # 2. Direct IDOR Access rejection: User A cannot read User B's conversation (returns 404)
        idor_get = client.get(f"/api/conversations/{conv_b_id}", headers={"Authorization": f"Bearer {token_a}"})
        assert idor_get.status_code == 404

        # 3. Direct IDOR Update rejection: User A cannot rename User B's conversation
        idor_patch = client.patch(
            f"/api/conversations/{conv_b_id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"title": "Hacked Title"},
        )
        assert idor_patch.status_code == 404

        # 4. Direct IDOR Delete rejection: User A cannot delete User B's conversation
        idor_delete = client.delete(f"/api/conversations/{conv_b_id}", headers={"Authorization": f"Bearer {token_a}"})
        assert idor_delete.status_code == 404

        # 5. Direct IDOR Message injection rejection: User A cannot post to User B's conversation
        idor_msg = client.post(
            f"/api/conversations/{conv_b_id}/messages",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"question": "Sneaky message"},
        )
        assert idor_msg.status_code == 404

