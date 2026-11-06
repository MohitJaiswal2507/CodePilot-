"""
Safe recovery procedure for quarantined legacy documents.
Allows an administrator or verified owner to claim quarantined documents,
reassigning them to an authenticated user_id in ChromaDB and inserting
the corresponding metadata record in PostgreSQL.
"""
import sys
import argparse
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.vector_store import VectorStoreService
from app.db.session import SessionLocal
from app.models.document import Document
import uuid

def recover_documents(target_user_id: str, document_name: str = None):
    vs = VectorStoreService.get_instance()
    db = SessionLocal()

    try:
        # 1. Reassign in ChromaDB
        reassigned_count = vs.reassign_quarantined_documents(
            target_user_id=target_user_id,
            document_name=document_name,
        )
        print(f"Reassigned {reassigned_count} chunks in ChromaDB to user '{target_user_id}'.")

        # 2. Get document summaries from ChromaDB for the user to register in PostgreSQL
        user_docs = vs.list_documents(user_id=target_user_id)
        for doc_sum in user_docs:
            if document_name and doc_sum.document_name != document_name:
                continue

            existing = db.query(Document).filter(
                Document.owner_user_id == target_user_id,
                Document.original_filename == doc_sum.document_name,
            ).first()

            if not existing:
                doc_record = Document(
                    id=str(uuid.uuid4()),
                    owner_user_id=target_user_id,
                    original_filename=doc_sum.document_name,
                    upload_status="completed",
                    processing_status="indexed",
                    total_pages=doc_sum.total_pages,
                    total_chunks=doc_sum.total_chunks,
                    file_size_bytes=doc_sum.file_size_bytes,
                )
                db.add(doc_record)
                db.commit()
                print(f"Registered document record in PostgreSQL: {doc_sum.document_name} ({doc_sum.total_chunks} chunks).")
            else:
                existing.total_chunks = doc_sum.total_chunks
                existing.total_pages = doc_sum.total_pages
                db.commit()
                print(f"Updated existing document record in PostgreSQL: {doc_sum.document_name}.")

    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover quarantined documents for an authenticated user.")
    parser.add_argument("--target-user-id", required=True, help="Authenticated user ID to assign documents to.")
    parser.add_argument("--document-name", required=False, default=None, help="Specific document name to assign (optional).")
    args = parser.parse_args()

    recover_documents(target_user_id=args.target_user_id, document_name=args.document_name)

