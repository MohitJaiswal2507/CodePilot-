import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, AuthenticatedUser
from app.db.session import get_db
from app.models.code_review import CodeReview
from app.schemas.reviewer import (
    ReviewCodeRequest,
    CodeReviewResponse,
    CodeReviewHistoryResponse,
    CodeReviewHistoryItem,
    CodeReviewResult,
)
from app.services.review_graph import execute_code_review
from app.services import model_service
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviewer", tags=["AI Code Reviewer"])


def _commit_db_write(
    db: Session,
    *,
    action: str,
    owner_user_id: str,
    client_detail: str,
) -> None:
    """Commit a database write with explicit rollback and sanitized 500 error handling."""
    try:
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Database persistence failed during %s for user_id=%s", action, owner_user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=client_detail,
        )

@router.post("/review", response_model=CodeReviewResponse, status_code=status.HTTP_201_CREATED)
def submit_code_review(
    payload: ReviewCodeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeReviewResponse:
    """
    Execute AI Code Review using the LangGraph stateful workflow:
    1. Validate authenticated user identity.
    2. Validate language and input constraints.
    3. Run LangGraph workflow: validation -> static inspection -> AI review -> edge-case analysis -> complexity analysis -> format.
    4. Persist structured review in PostgreSQL owned by current_user.user_id.
    5. Return validated structured result.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    code = payload.code.strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Submitted code cannot be empty.",
        )

    language = payload.language.lower().strip()
    if language not in ("python", "java", "cpp"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported language '{payload.language}'. Supported languages: Python, Java, C++.",
        )

    # Validate selected Gemini model
    selected_model: Optional[str] = None
    if payload.model:
        try:
            selected_model = model_service.validate_model_id(payload.model)
        except ValueError as val_err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(val_err)
            )

    active_model = selected_model or settings.GEMINI_MODEL or "gemini-2.5-flash"

    logger.info(
        "DIAGNOSTIC: Code review requested by user_id=%s, language=%s, model=%s, code_len=%d",
        owner_user_id,
        language,
        active_model,
        len(code),
    )

    try:
        review_result = execute_code_review(
            code=code,
            language=language,
            user_id=owner_user_id,
            model=active_model,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Code review execution failed for user_id=%s, language=%s, model=%s",
            owner_user_id,
            language,
            active_model,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete code review due to an unexpected internal error.",
        )

    # Persist in PostgreSQL
    review_id = str(uuid.uuid4())
    try:
        db_record = CodeReview(
            id=review_id,
            owner_user_id=owner_user_id,
            language=language,
            submitted_code=code,
            structured_result=review_result.model_dump(),
            model_used=active_model,
        )
        db.add(db_record)
        _commit_db_write(
            db,
            action="submit_code_review",
            owner_user_id=owner_user_id,
            client_detail="Failed to save code review due to an internal error.",
        )
        db.refresh(db_record)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception(
            "Code review persistence failed for user_id=%s, review_id=%s",
            owner_user_id,
            review_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save code review due to an internal error.",
        )

    logger.info(
        "DIAGNOSTIC: Code review completed and persisted: review_id=%s, user_id=%s, score=%d/10",
        review_id,
        owner_user_id,
        review_result.quality_score,
    )

    return CodeReviewResponse(
        id=review_id,
        language=language,
        submitted_code=code,
        review=review_result,
        model_used=active_model,
        created_at=db_record.created_at.isoformat() if db_record.created_at else "",
    )


@router.get("/history", response_model=CodeReviewHistoryResponse)
def list_code_reviews(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeReviewHistoryResponse:
    """
    List previous code reviews owned strictly by the authenticated user.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    query = db.query(CodeReview).filter(CodeReview.owner_user_id == owner_user_id)
    total = query.count()
    records = query.order_by(CodeReview.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for r in records:
        data = r.structured_result or {}
        snippet = r.submitted_code[:120].strip() + ("..." if len(r.submitted_code) > 120 else "")
        items.append(
            CodeReviewHistoryItem(
                id=r.id,
                language=r.language,
                code_snippet=snippet,
                summary=data.get("summary", "Code review"),
                overall_assessment=data.get("overall_assessment", "good"),
                quality_score=data.get("quality_score", 7),
                model_used=r.model_used,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
        )

    return CodeReviewHistoryResponse(reviews=items, total=total)


@router.get("/{review_id}", response_model=CodeReviewResponse)
def get_code_review(
    review_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeReviewResponse:
    """
    Retrieve full details of a specific code review.
    Enforces strict ownership check: returns 404 if not found or owned by another user.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    record = (
        db.query(CodeReview)
        .filter(
            CodeReview.id == review_id,
            CodeReview.owner_user_id == owner_user_id,
        )
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Code review '{review_id}' not found in your workspace.",
        )

    result = CodeReviewResult.model_validate(record.structured_result)

    return CodeReviewResponse(
        id=record.id,
        language=record.language,
        submitted_code=record.submitted_code,
        review=result,
        model_used=record.model_used,
        created_at=record.created_at.isoformat() if record.created_at else "",
    )


@router.delete("/{review_id}", status_code=status.HTTP_200_OK)
def delete_code_review(
    review_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a specific review owned by the authenticated user.
    Cross-user deletion attempts are rejected with 404.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    record = (
        db.query(CodeReview)
        .filter(
            CodeReview.id == review_id,
            CodeReview.owner_user_id == owner_user_id,
        )
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Code review '{review_id}' not found in your workspace.",
        )

    db.delete(record)
    _commit_db_write(
        db,
        action="delete_code_review",
        owner_user_id=owner_user_id,
        client_detail="Failed to delete code review due to an internal error.",
    )

    return {
        "status": "success",
        "message": f"Code review '{review_id}' deleted successfully.",
    }


@router.delete("", status_code=status.HTTP_200_OK)
def clear_code_review_history(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Clear all code reviews belonging strictly to the calling user.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    deleted_count = (
        db.query(CodeReview)
        .filter(CodeReview.owner_user_id == owner_user_id)
        .delete()
    )
    _commit_db_write(
        db,
        action="clear_code_review_history",
        owner_user_id=owner_user_id,
        client_detail="Failed to clear code review history due to an internal error.",
    )

    return {
        "status": "success",
        "message": f"Successfully deleted {deleted_count} code review(s) from your history.",
    }

