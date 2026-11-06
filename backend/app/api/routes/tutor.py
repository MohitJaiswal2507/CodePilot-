import uuid
import logging
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, AuthenticatedUser
from app.db.session import get_db
from app.models.document import Document
from app.schemas.tutor import (
    UploadResponse, 
    DocumentSummary, 
    DocumentListResponse, 
    QueryRequest, 
    QueryResponse,
    ModelListResponse,
)
from app.services.pdf_service import validate_pdf, extract_text_by_page, chunk_document
from app.services.vector_store import VectorStoreService
from app.services.rag_service import answer_question
from app.services import model_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tutor", tags=["AI Learning Tutor"])

@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """
    Ingest a PDF course document with strict authenticated user ownership:
    1. Verify authenticated user identity (never trust client-supplied owner ID).
    2. Validate and extract text from the PDF.
    3. Generate text chunks.
    4. Persist document metadata record in PostgreSQL owned by current_user.user_id.
    5. Persist chunk embeddings in ChromaDB tagged with user_id and document_id.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    filename = file.filename or "uploaded_document.pdf"
    
    # Development diagnostic log (no secrets/tokens logged)
    logger.info(
        "DIAGNOSTIC: PDF upload initiated by user_id=%s (email=%s, role=%s) for file=%s",
        owner_user_id,
        current_user.email,
        current_user.role,
        filename,
    )
    
    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {exc}"
        )

    # 1. Validation
    try:
        validate_pdf(file_bytes, filename)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )

    # 2. Text Extraction
    try:
        pages = extract_text_by_page(file_bytes, filename)
    except ValueError as ext_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ext_err)
        )

    # 3. Intelligent Chunking
    chunks = chunk_document(pages, filename)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to generate any valid text chunks from this document."
        )

    # 4. Check for existing document by same user with same filename (overwrite/re-upload)
    vector_store = VectorStoreService.get_instance()
    existing_doc = db.query(Document).filter(
        Document.owner_user_id == owner_user_id,
        Document.original_filename == filename,
    ).first()

    if existing_doc:
        logger.info(
            "DIAGNOSTIC: Overwriting existing document id=%s for user_id=%s, filename=%s",
            existing_doc.id,
            owner_user_id,
            filename,
        )
        vector_store.delete_document(user_id=owner_user_id, document_identifier=filename)
        vector_store.delete_document(user_id=owner_user_id, document_identifier=existing_doc.id)
        db.delete(existing_doc)
        db.commit()

    # 5. Create initial PostgreSQL record
    doc_id = str(uuid.uuid4())
    doc_record = Document(
        id=doc_id,
        owner_user_id=owner_user_id,
        original_filename=filename,
        upload_status="processing",
        processing_status="indexing",
        total_pages=len(pages),
        total_chunks=len(chunks),
        file_size_bytes=len(file_bytes),
    )
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)

    # 6. Index Chunks in Vector Store with verified user ownership
    try:
        vector_store.add_document_chunks(
            chunks=chunks,
            user_id=owner_user_id,
            document_id=doc_id,
            file_size_bytes=len(file_bytes),
        )
    except Exception as store_err:
        logger.error("Failed to index chunks for doc_id=%s, user_id=%s: %s", doc_id, owner_user_id, store_err)
        doc_record.upload_status = "failed"
        doc_record.processing_status = f"error: {str(store_err)[:100]}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index document in vector store: {store_err}"
        )

    # 7. Mark processing as completed
    doc_record.upload_status = "completed"
    doc_record.processing_status = "indexed"
    db.commit()
    db.refresh(doc_record)

    logger.info(
        "DIAGNOSTIC: PDF upload success: doc_id=%s, owner_user_id=%s, chunks=%d, pages=%d",
        doc_id,
        owner_user_id,
        len(chunks),
        len(pages),
    )

    summary = DocumentSummary(
        id=doc_id,
        document_name=filename,
        owner_user_id=owner_user_id,
        total_pages=len(pages),
        total_chunks=len(chunks),
        file_size_bytes=len(file_bytes),
        uploaded_at=doc_record.created_at.isoformat() if doc_record.created_at else "",
        upload_status="completed",
    )

    return UploadResponse(
        status="success",
        message=f"Document '{filename}' successfully processed and indexed ({len(chunks)} chunks across {len(pages)} pages).",
        document=summary,
    )

@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    """
    List learning materials belonging strictly to the authenticated user.
    Uses PostgreSQL as the authoritative source of document ownership,
    guaranteeing that no user can see or enumerate documents uploaded by other accounts.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    # Development diagnostic log
    logger.info(
        "DIAGNOSTIC: list_documents requested by user_id=%s (email=%s)",
        owner_user_id,
        current_user.email,
    )

    # Strict ownership query on PostgreSQL
    user_docs = (
        db.query(Document)
        .filter(
            Document.owner_user_id == owner_user_id,
            Document.upload_status == "completed",
        )
        .order_by(Document.created_at.desc())
        .all()
    )

    summaries = [
        DocumentSummary(
            id=d.id,
            document_name=d.original_filename,
            total_pages=d.total_pages,
            total_chunks=d.total_chunks,
            file_size_bytes=d.file_size_bytes,
            uploaded_at=d.created_at.isoformat() if d.created_at else "",
            owner_user_id=d.owner_user_id,
            upload_status=d.upload_status,
        )
        for d in user_docs
    ]
    total_chunks = sum(d.total_chunks for d in summaries)

    logger.info(
        "DIAGNOSTIC: list_documents returning %d documents, %d total chunks for user_id=%s",
        len(summaries),
        total_chunks,
        owner_user_id,
    )

    return DocumentListResponse(
        documents=summaries,
        total_documents=len(summaries),
        total_chunks=total_chunks,
    )

@router.delete("/documents/{document_identifier}")
def delete_document(
    document_identifier: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a specific document and its vector embeddings.
    Strictly verifies that the document belongs to the authenticated user.
    Cross-user deletion attempts are rejected with 404.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    logger.info(
        "DIAGNOSTIC: delete_document requested for identifier='%s' by user_id=%s",
        document_identifier,
        owner_user_id,
    )

    # Find the document owned strictly by this user (by ID or filename)
    doc = (
        db.query(Document)
        .filter(
            Document.owner_user_id == owner_user_id,
            (Document.id == document_identifier) | (Document.original_filename == document_identifier),
        )
        .first()
    )

    if not doc:
        logger.warning(
            "DIAGNOSTIC: delete_document REJECTED: document '%s' not found for user_id=%s",
            document_identifier,
            owner_user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_identifier}' not found in your learning materials.",
        )

    doc_name = doc.original_filename
    doc_id = doc.id

    # 1. Delete from ChromaDB
    vector_store = VectorStoreService.get_instance()
    vector_store.delete_document(user_id=owner_user_id, document_identifier=doc_name)
    vector_store.delete_document(user_id=owner_user_id, document_identifier=doc_id)

    # 2. Delete from PostgreSQL
    db.delete(doc)
    db.commit()

    logger.info(
        "DIAGNOSTIC: delete_document SUCCESS: deleted doc_id=%s, name='%s' for user_id=%s",
        doc_id,
        doc_name,
        owner_user_id,
    )

    return {
        "status": "success",
        "message": f"Document '{doc_name}' deleted successfully.",
    }

@router.delete("/documents")
def clear_all_documents(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Clear all documents and embeddings belonging STRICTLY to the calling user.
    NEVER deletes or affects documents belonging to any other user.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    logger.info("DIAGNOSTIC: clear_all_documents requested by user_id=%s", owner_user_id)

    # 1. Clear user chunks from ChromaDB
    vector_store = VectorStoreService.get_instance()
    deleted_chunks = vector_store.clear_user_documents(user_id=owner_user_id)

    # 2. Clear user records from PostgreSQL
    deleted_records = (
        db.query(Document)
        .filter(Document.owner_user_id == owner_user_id)
        .delete()
    )
    db.commit()

    logger.info(
        "DIAGNOSTIC: clear_all_documents SUCCESS: removed %d records and %d vector chunks for user_id=%s",
        deleted_records,
        deleted_chunks,
        owner_user_id,
    )

    return {
        "status": "success",
        "message": f"Successfully removed {deleted_records} document(s) from your workspace.",
    }

@router.get("/models", response_model=ModelListResponse)
def list_models(
    refresh: bool = False,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ModelListResponse:
    """
    Retrieve available Gemini models that support generateContent,
    with caching and manual refresh support.
    """
    return model_service.get_available_models(refresh=refresh)

@router.post("/query", response_model=QueryResponse)
def query_tutor(
    payload: QueryRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> QueryResponse:
    """
    RAG Query Endpoint with strict multi-user context isolation:
    Retrieve context chunks from uploaded documents belonging strictly to current_user.user_id,
    construct a grounded prompt, call the selected Gemini model, and return answer with verified citations.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
        )

    logger.info(
        "DIAGNOSTIC: query_tutor requested by user_id=%s, filter=%s, question_snippet='%s'",
        owner_user_id,
        payload.document_filter,
        payload.question[:60],
    )

    # Validate selected model if provided
    selected_model: Optional[str] = None
    if payload.model:
        try:
            selected_model = model_service.validate_model_id(payload.model)
        except ValueError as val_err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(val_err)
            )

    return answer_question(
        question=payload.question,
        user_id=owner_user_id,
        document_filter=payload.document_filter,
        top_k=payload.top_k,
        history=payload.history,
        model=selected_model,
    )
