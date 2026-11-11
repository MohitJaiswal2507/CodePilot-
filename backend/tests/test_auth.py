import json
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


@pytest.fixture
def isolated_conversation_users():
    """
    Create unique synthetic test user IDs per run and delete only their
    test conversations/messages on teardown without touching any real data.
    """
    user_a = f"test_alpha_{uuid.uuid4().hex[:12]}"
    user_b = f"test_beta_{uuid.uuid4().hex[:12]}"
    yield user_a, user_b

    db = SessionLocal()
    try:
        conv_ids = [
            row[0]
            for row in db.query(Conversation.id)
            .filter(Conversation.user_id.in_([user_a, user_b]))
            .all()
        ]
        if conv_ids:
            db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(
                synchronize_session=False
            )
            db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(
                synchronize_session=False
            )
            db.commit()
    finally:
        db.close()


# -----------------------------------------------------------------------------
# 2. Multi-Tenant User Isolation & IDOR Protection Tests
# -----------------------------------------------------------------------------
@patch("app.core.auth.get_jwks_client")
def test_user_owned_conversations_strict_isolation(mock_jwks, isolated_conversation_users):
    user_a, user_b = isolated_conversation_users

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


# -----------------------------------------------------------------------------
# 3. Regression Tests: Fail-Closed JWT Key Resolution & Forged Token Rejection
# -----------------------------------------------------------------------------
def _make_eddsa_token_with_kid(
    user_id: str,
    kid: str | None = None,
    key=None,
    issuer: str | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": f"{user_id}@codepilot.ai",
        "iat": now - 10,
        "exp": now + 3600,
    }
    effective_iss = issuer if issuer is not None else settings.NEON_AUTH_ISSUER
    if effective_iss:
        payload["iss"] = effective_iss
    if settings.NEON_AUTH_AUDIENCE:
        payload["aud"] = settings.NEON_AUTH_AUDIENCE
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(payload, key or ed_private_key, algorithm="EdDSA", headers=headers)


def _real_jwks_client_for_ed_key(expected_kid: str = "neon-kid-1") -> jwt.PyJWKClient:
    """Create a real PyJWKClient backed by an in-memory JWK (zero network I/O)."""
    jwk_dict = jwt.PyJWK.from_dict(
        json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(ed_public_key))
        | {"kid": expected_kid, "use": "sig", "alg": "EdDSA"}
    )
    jwks_client = jwt.PyJWKClient("https://mocked.local/.well-known/jwks.json", cache_jwk_set=False)
    jwks_client.get_signing_keys = MagicMock(return_value=[jwk_dict])  # type: ignore[method-assign]
    return jwks_client


@pytest.mark.parametrize("env_name", ["development", "production"])
def test_unknown_and_missing_kid_rejected_with_401(env_name):
    jwks_client = _real_jwks_client_for_ed_key("neon-kid-1")
    valid_token = _make_eddsa_token_with_kid("alice", kid="neon-kid-1")
    unknown_kid_token = _make_eddsa_token_with_kid("alice", kid="unknown-kid-999")
    missing_kid_token = _make_eddsa_token_with_kid("alice", kid=None)

    with patch("app.core.auth.get_jwks_client", return_value=jwks_client), \
         patch.object(settings, "ENVIRONMENT", env_name), \
         patch.object(settings, "ALLOW_DEV_FALLBACK_AUTH", True):
        ok_res = client.get("/api/conversations", headers={"Authorization": f"Bearer {valid_token}"})
        assert ok_res.status_code == 200

        res_unknown = client.get("/api/conversations", headers={"Authorization": f"Bearer {unknown_kid_token}"})
        assert res_unknown.status_code == 401

        res_missing = client.get("/api/conversations", headers={"Authorization": f"Bearer {missing_kid_token}"})
        assert res_missing.status_code == 401


@pytest.mark.parametrize("env_name", ["development", "production"])
def test_jwks_exception_and_empty_db_fallback_rejected_with_401(env_name):
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("JWKS endpoint unreachable")
    forged_token = _make_eddsa_token_with_kid("victim_user_id", kid="forged-kid", key=ed25519.Ed25519PrivateKey.generate())

    # Simulated DB session whose neon_auth.jwks query returns no matching row
    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.first.return_value = None

    from app.core.auth import verify_neon_jwt
    from fastapi import HTTPException

    with patch("app.core.auth.get_jwks_client", return_value=mock_client), \
         patch.object(settings, "ENVIRONMENT", env_name), \
         patch.object(settings, "ALLOW_DEV_FALLBACK_AUTH", True):
        # Direct verifier check with DB returning None
        with pytest.raises(HTTPException) as exc_info:
            verify_neon_jwt(forged_token, db=mock_db)
        assert exc_info.value.status_code == 401
        mock_db.execute.assert_called_once()

        # Route-level check
        res = client.get("/api/conversations", headers={"Authorization": f"Bearer {forged_token}"})
        assert res.status_code == 401


def test_missing_kid_does_not_bypass_via_db_jwks_lookup():
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError('Unable to find a signing key that matches: "None"')
    missing_kid_token = _make_eddsa_token_with_kid("alice", kid=None)

    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.first.return_value = {
        "publicKey": ed_public_key,
    }

    from app.core.auth import verify_neon_jwt
    from fastapi import HTTPException

    with patch("app.core.auth.get_jwks_client", return_value=mock_client), \
         patch.object(settings, "ENVIRONMENT", "production"):
        with pytest.raises(HTTPException) as exc_info:
            verify_neon_jwt(missing_kid_token, db=mock_db)
        assert exc_info.value.status_code == 401
        mock_db.execute.assert_not_called()


@pytest.mark.parametrize("endpoint,method,body", [
    ("/api/conversations", "GET", None),
    ("/api/reviewer/history", "GET", None),
    ("/api/v1/sandbox/execute", "POST", {"code": "print(1)", "language": "python"}),
])
def test_forged_jwt_with_victim_sub_cannot_access_protected_endpoints(endpoint, method, body):
    jwks_client = _real_jwks_client_for_ed_key("neon-kid-1")
    attacker_private_key = ed25519.Ed25519PrivateKey.generate()
    # Forge a JWT claiming victim_sub with unknown kid (previously disabled verify_signature)
    forged_unknown_kid = _make_eddsa_token_with_kid(
        "victim_user_alice",
        kid="attacker-kid",
        key=attacker_private_key,
    )
    # Also test HS256 forged with >=32-byte secret + unknown kid, and alg="none"
    forged_hs256 = jwt.encode(
        {
            "sub": "victim_user_alice",
            "iat": int(time.time()) - 10,
            "exp": int(time.time()) + 3600,
            **({"iss": settings.NEON_AUTH_ISSUER} if settings.NEON_AUTH_ISSUER else {}),
        },
        "insecure-dev-fallback-secret-for-test-only",
        algorithm="HS256",
        headers={"kid": "attacker-hs-kid"},
    )
    forged_alg_none = jwt.encode(
        {
            "sub": "victim_user_alice",
            "iat": int(time.time()) - 10,
            "exp": int(time.time()) + 3600,
        },
        "",
        algorithm="none",
    )

    with patch("app.core.auth.get_jwks_client", return_value=jwks_client), \
         patch.object(settings, "ENVIRONMENT", "development"), \
         patch.object(settings, "ALLOW_DEV_FALLBACK_AUTH", True):
        for token in (forged_unknown_kid, forged_hs256, forged_alg_none):
            headers = {"Authorization": f"Bearer {token}"}
            if method == "GET":
                res = client.get(endpoint, headers=headers)
            else:
                res = client.post(endpoint, headers=headers, json=body)
            assert res.status_code == 401

