import logging
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pydantic import BaseModel
import jwt
from jwt import PyJWKClient, PyJWTError, ExpiredSignatureError, InvalidSignatureError, InvalidIssuerError
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)

# Security scheme for Bearer token extraction
security = HTTPBearer(auto_error=False)

class AuthenticatedUser(BaseModel):
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = "user"
    token_type: str = "bearer"
    claims: Dict[str, Any] = {}

# In-memory cached PyJWKClient
_jwks_client: Optional[PyJWKClient] = None
_jwks_client_url: Optional[str] = None

def get_jwks_client() -> PyJWKClient:
    """Return a cached PyJWKClient configured with Neon Auth JWKS endpoint."""
    global _jwks_client, _jwks_client_url
    url = settings.resolved_jwks_url
    if _jwks_client is None or _jwks_client_url != url:
        _jwks_client = PyJWKClient(url, cache_jwk_set=True, lifespan=3600)
        _jwks_client_url = url
    return _jwks_client


def verify_neon_jwt(token: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Verify a Neon Auth JWT strictly with cryptographic signature verification:
    1. Extracts signing key from remote Neon Auth JWKS endpoint (with caching & rotation support).
    2. Optional fallback: Looks up matching `kid` in local `neon_auth.jwks` table when DB session is provided.
    3. Fails closed with HTTP 401 whenever no signing key can be resolved (never decodes unverified JWTs).
    4. Validates signature (`verify_signature=True`), allowed algorithms, expiration, and issuer/audience.
    """
    allowed_algs = ["EdDSA", "RS256", "ES256", "HS256"]

    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Malformed JWT header: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    signing_alg = unverified_header.get("alg")
    if not signing_alg or signing_alg not in allowed_algs:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported or missing signing algorithm: '{signing_alg}'. Allowed algorithms: {allowed_algs}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    signing_key = None
    jwks_error = None

    # Step A: Try fetching key via official Neon Auth JWKS client
    try:
        client = get_jwks_client()
        signing_key_obj = client.get_signing_key_from_jwt(token)
        signing_key = signing_key_obj.key
    except Exception as exc:
        jwks_error = exc
        logger.debug("Remote JWKS resolution failed: %s; checking database JWKS fallback", exc)

    # Step B: Fallback to neon_auth.jwks table by exact `kid` if database session is provided
    raw_kid = unverified_header.get("kid")
    kid = raw_kid.strip() if isinstance(raw_kid, str) else None
    if signing_key is None and db is not None and kid:
        try:
            result = db.execute(
                text(
                    """
                    SELECT publicKey FROM neon_auth.jwks
                    WHERE id = :kid
                    ORDER BY createdAt DESC LIMIT 1;
                    """
                ),
                {"kid": kid},
            ).mappings().first()
            if result and result.get("publicKey"):
                signing_key = result["publicKey"]
        except Exception as db_exc:
            logger.debug("Database JWKS lookup failed: %s", db_exc)

    # Always fail closed if no signing key was resolved; never decode an unverified JWT.
    if not signing_key:
        if jwks_error is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Could not verify token against Neon Auth JWKS: {str(jwks_error)}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token: signing key could not be resolved.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_nbf": True,
        "verify_iat": True,
        "verify_aud": bool(settings.NEON_AUTH_AUDIENCE),
        "verify_iss": bool(settings.NEON_AUTH_ISSUER),
    }

    try:
        payload = jwt.decode(
            token,
            key=signing_key,
            algorithms=allowed_algs,
            options=options,
            issuer=settings.NEON_AUTH_ISSUER if settings.NEON_AUTH_ISSUER else None,
            audience=settings.NEON_AUTH_AUDIENCE if settings.NEON_AUTH_AUDIENCE else None,
            leeway=60,
        )
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"token has expired\""},
        )
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature. Token verification failed.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"invalid signature\""},
        )
    except InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token issuer mismatch.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"invalid issuer\""},
        )
    except PyJWTError as e:
        # If remote JWKS failed and signature couldn't be checked
        if signing_key is None and jwks_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Could not verify token against Neon Auth JWKS: {str(jwks_error)}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_session_token(token: str, db: Session) -> Optional[AuthenticatedUser]:
    """
    Verify an active session token against Neon Auth's neon_auth.session and neon_auth.user tables.
    Used when frontend passes session cookies or session tokens.
    """
    try:
        session_row = db.execute(
            text("""
                SELECT s.id as session_id, s."userId" as user_id, s."expiresAt" as expires_at,
                       u.email, u.name, u.role
                FROM neon_auth.session s
                LEFT JOIN neon_auth.user u ON s."userId" = u.id
                WHERE s.token = :token;
            """),
            {"token": token}
        ).mappings().first()

        if not session_row:
            return None

        # Check expiration
        expires_at = session_row["expires_at"]
        if expires_at and expires_at < datetime.now(timezone.utc):
            return None

        return AuthenticatedUser(
            user_id=str(session_row["user_id"]),
            email=session_row.get("email"),
            name=session_row.get("name"),
            role=session_row.get("role") or "user",
            token_type="session",
            claims={"session_id": str(session_row["session_id"])}
        )
    except Exception as exc:
        logger.debug("Session token verification error: %s", exc)
        return None


def get_current_user(
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """
    FastAPI reusable dependency:
    Extracts Bearer token from Authorization header and verifies it via Neon Auth JWKS or session store.
    Extracts and returns verified user identity with subject claim ('sub').
    Raises HTTP 401 Unauthorized for missing, malformed, invalid, or expired credentials.
    """
    if not auth_header or not auth_header.credentials:
        if settings.ENVIRONMENT == "test" and settings.ALLOW_DEV_FALLBACK_AUTH:
            effective_user = f"user_{x_session_id}" if x_session_id else "test_default_user_1"
            return AuthenticatedUser(
                user_id=effective_user,
                email=f"{effective_user}@codepilot.ai",
                name="Test User",
                role="user",
                token_type="test",
                claims={"sub": effective_user},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please include 'Authorization: Bearer <token>' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = auth_header.credentials.strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty authorization token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Try JWT verification (Neon Auth standard access token)
    if raw_token.count(".") == 2:
        try:
            payload = verify_neon_jwt(raw_token, db=db)
            sub = payload.get("sub") or payload.get("userId") or payload.get("id")
            if not sub:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: missing subject claim ('sub').",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return AuthenticatedUser(
                user_id=str(sub),
                email=payload.get("email"),
                name=payload.get("name"),
                role=payload.get("role", "user"),
                token_type="jwt",
                claims=payload,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("JWT verification failed: %s; checking session table", exc)

    # 2. Check if token is a direct session token from neon_auth.session
    user_from_session = verify_session_token(raw_token, db=db)
    if user_from_session:
        return user_from_session

    # If neither JWT nor session token validated
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or unrecognized authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
