import os
import math
import uuid
import threading
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Sequence

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document_chunk import DocumentChunkModel
from app.schemas.tutor import DocumentChunk, DocumentSummary
from app.services.embedding_provider import (
    EmbeddingProvider,
    get_embedding_provider,
)

logger = logging.getLogger(__name__)


def _cosine_distance(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Compute cosine distance (1 - cosine_similarity) between two vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 <= 1e-9 or norm2 <= 1e-9:
        return 1.0
    cosine_sim = dot / (norm1 * norm2)
    return max(0.0, 1.0 - cosine_sim)


class VectorStoreService:
    """
    ChromaDB-backed vector store for local development and testing.
    Also acts as default vector store facade.
    """
    _instance: Optional["VectorStoreService"] = None
    _lock = threading.Lock()

    def __init__(self, persist_dir: str = None, model_name: str = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self._embedder: Optional[SentenceTransformer] = None
        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self._client.get_or_create_collection(
            name="codepilot_materials",
            metadata={"hnsw:space": "cosine"}
        )

    @classmethod
    def get_instance(cls) -> "VectorStoreService":
        backend = (settings.VECTOR_STORE_BACKEND or "chroma").lower().strip()
        if backend == "pgvector":
            return PgVectorStoreService.get_instance()

        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            with self._lock:
                if self._embedder is None:
                    self._embedder = SentenceTransformer(self.model_name)
        return self._embedder

    def add_document_chunks(
        self,
        chunks: List[DocumentChunk],
        user_id: str,
        document_id: str,
        file_size_bytes: int = 0,
    ) -> None:
        """
        Encode chunks and insert into persistent ChromaDB collection with strict user ownership.
        Both user_id and document_id are mandatory.
        """
        if not chunks:
            return

        clean_user_id = str(user_id).strip() if user_id else ""
        clean_doc_id = str(document_id).strip() if document_id else ""

        if not clean_user_id:
            raise ValueError("user_id is strictly required for document indexing into vector store")
        if not clean_doc_id:
            raise ValueError("document_id is strictly required for document indexing into vector store")

        texts = [chunk.text for chunk in chunks]
        embeddings = self.embedder.encode(texts, show_progress_bar=False).tolist()

        ids = [f"{clean_user_id}_{chunk.id}" for chunk in chunks]
        now_iso = datetime.now(timezone.utc).isoformat()
        metadatas = [
            {
                "user_id": clean_user_id,
                "document_id": clean_doc_id,
                "chunk_id": str(chunk.id),
                "document_name": str(chunk.document_name),
                "source_filename": str(chunk.document_name),
                "page_number": int(chunk.page_number),
                "chunk_index": int(chunk.chunk_index),
                "file_size_bytes": int(file_size_bytes),
                "uploaded_at": now_iso,
            }
            for chunk in chunks
        ]

        logger.info(
            "ChromaDB indexing: user_id=%s, document_id=%s, chunks_count=%d",
            clean_user_id,
            clean_doc_id,
            len(chunks),
        )

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    def similarity_search(
        self,
        query: str,
        user_id: str,
        top_k: int = 4,
        document_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve most relevant chunks using cosine similarity.
        STRICT SECURITY RULE: user_id is mandatory. No un-isolated global searches permitted.
        """
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id:
            raise ValueError("user_id is strictly required for similarity search to maintain data isolation")

        count = self.collection.count()
        if count == 0:
            return []

        if document_filter:
            clean_filter = str(document_filter).strip()
            where_filter = {
                "$and": [
                    {"user_id": clean_user_id},
                    {"document_name": clean_filter},
                ]
            }
        else:
            where_filter = {"user_id": clean_user_id}

        query_embedding = self.embedder.encode([query], show_progress_bar=False).tolist()

        try:
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning(
                "ChromaDB similarity_search query failed with filter %s: %s",
                where_filter,
                exc,
            )
            return []

        retrieved: List[Dict[str, Any]] = []
        if not results or not results.get("documents") or not results["documents"][0]:
            return []

        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

        for doc_text, meta, dist in zip(docs, metas, distances):
            similarity = round(1.0 - float(dist), 4)
            retrieved.append({
                "text": doc_text,
                "document_name": meta.get("document_name", "Unknown"),
                "source_filename": meta.get("source_filename", meta.get("document_name", "Unknown")),
                "document_id": meta.get("document_id"),
                "chunk_id": meta.get("chunk_id"),
                "user_id": meta.get("user_id"),
                "page_number": meta.get("page_number", 1),
                "chunk_index": meta.get("chunk_index", 0),
                "similarity": similarity,
                "distance": dist,
            })

        logger.info(
            "ChromaDB retrieval: user_id=%s, query_len=%d, retrieved_count=%d",
            clean_user_id,
            len(query),
            len(retrieved),
        )
        return retrieved

    def list_documents(self, user_id: str) -> List[DocumentSummary]:
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id:
            return []

        results = self.collection.get(
            where={"user_id": clean_user_id},
            include=["metadatas"],
        )
        if not results or not results.get("metadatas"):
            return []

        docs_map: Dict[str, Dict[str, Any]] = {}
        for meta in results["metadatas"]:
            doc_name = meta.get("document_name", "Unknown")
            doc_id = meta.get("document_id")
            key = doc_id or doc_name

            if key not in docs_map:
                docs_map[key] = {
                    "id": doc_id,
                    "document_name": doc_name,
                    "owner_user_id": clean_user_id,
                    "pages": set(),
                    "total_chunks": 0,
                    "file_size_bytes": meta.get("file_size_bytes", 0),
                    "uploaded_at": meta.get("uploaded_at", datetime.now(timezone.utc).isoformat()),
                }
            docs_map[key]["pages"].add(meta.get("page_number", 1))
            docs_map[key]["total_chunks"] += 1

        summaries = [
            DocumentSummary(
                id=item["id"],
                document_name=item["document_name"],
                total_pages=len(item["pages"]),
                total_chunks=item["total_chunks"],
                file_size_bytes=item["file_size_bytes"],
                uploaded_at=item["uploaded_at"],
                owner_user_id=clean_user_id,
            )
            for item in docs_map.values()
        ]
        return sorted(summaries, key=lambda s: s.uploaded_at, reverse=True)

    def delete_document(self, user_id: str, document_identifier: str) -> bool:
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id or not document_identifier:
            return False

        clean_ident = str(document_identifier).strip()

        existing_by_name = self.collection.get(
            where={
                "$and": [
                    {"user_id": clean_user_id},
                    {"document_name": clean_ident},
                ]
            }
        )
        if existing_by_name and existing_by_name.get("ids"):
            self.collection.delete(
                where={
                    "$and": [
                        {"user_id": clean_user_id},
                        {"document_name": clean_ident},
                    ]
                }
            )
            return True

        existing_by_id = self.collection.get(
            where={
                "$and": [
                    {"user_id": clean_user_id},
                    {"document_id": clean_ident},
                ]
            }
        )
        if existing_by_id and existing_by_id.get("ids"):
            self.collection.delete(
                where={
                    "$and": [
                        {"user_id": clean_user_id},
                        {"document_id": clean_ident},
                    ]
                }
            )
            return True

        return False

    def clear_user_documents(self, user_id: str) -> int:
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id:
            return 0

        existing = self.collection.get(where={"user_id": clean_user_id})
        if not existing or not existing.get("ids"):
            return 0

        count = len(existing["ids"])
        self.collection.delete(where={"user_id": clean_user_id})
        logger.info("ChromaDB clear_user_documents: user_id=%s, deleted_chunks=%d", clean_user_id, count)
        return count

    def quarantine_legacy_chunks(self) -> int:
        all_records = self.collection.get(include=["metadatas", "documents"])
        if not all_records or not all_records.get("ids"):
            return 0

        quarantined_ids = []
        quarantined_metas = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for chunk_id, meta in zip(all_records["ids"], all_records["metadatas"]):
            user_id = meta.get("user_id") if meta else None
            if not user_id or str(user_id).strip() in ("", "None", "unknown"):
                updated_meta = dict(meta) if meta else {}
                updated_meta["user_id"] = "__legacy_quarantined__"
                updated_meta["quarantined_at"] = now_iso
                quarantined_ids.append(chunk_id)
                quarantined_metas.append(updated_meta)

        if quarantined_ids:
            self.collection.update(
                ids=quarantined_ids,
                metadatas=quarantined_metas,
            )
            logger.info("Quarantined %d legacy chunks in ChromaDB", len(quarantined_ids))

        return len(quarantined_ids)

    def reassign_quarantined_documents(
        self,
        target_user_id: str,
        document_name: Optional[str] = None,
    ) -> int:
        clean_target = str(target_user_id).strip()
        if not clean_target:
            raise ValueError("target_user_id is required")

        where_filter = {"user_id": "__legacy_quarantined__"}
        if document_name:
            where_filter = {
                "$and": [
                    {"user_id": "__legacy_quarantined__"},
                    {"document_name": str(document_name).strip()},
                ]
            }

        records = self.collection.get(where=where_filter, include=["metadatas", "documents"])
        if not records or not records.get("ids"):
            return 0

        updated_ids = []
        updated_metas = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for chunk_id, meta in zip(records["ids"], records["metadatas"]):
            updated_meta = dict(meta)
            updated_meta["user_id"] = clean_target
            updated_meta["reassigned_at"] = now_iso
            updated_ids.append(chunk_id)
            updated_metas.append(updated_meta)

        self.collection.update(
            ids=updated_ids,
            metadatas=updated_metas,
        )
        logger.info(
            "Reassigned %d quarantined chunks to user_id=%s",
            len(updated_ids),
            clean_target,
        )
        return len(updated_ids)


ChromaVectorStoreService = VectorStoreService


class PgVectorStoreService:
    """
    PostgreSQL pgvector storage service for CodePilot AI RAG.
    Executes in-database cosine distance searches with HNSW index acceleration in PostgreSQL,
    and supports SQLite fallback for local offline testing.
    """
    _instance: Optional["PgVectorStoreService"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        expected_dimension: Optional[int] = None,
    ):
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.expected_dimension = expected_dimension or settings.EMBEDDING_DIMENSION or 768

    @classmethod
    def get_instance(cls) -> "PgVectorStoreService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for test isolation."""
        with cls._lock:
            cls._instance = None

    def add_document_chunks(
        self,
        chunks: List[DocumentChunk],
        user_id: str,
        document_id: str,
        file_size_bytes: int = 0,
    ) -> None:
        """
        Embed chunks and insert into PostgreSQL document_chunks table with strict user ownership.
        """
        if not chunks:
            return

        clean_user_id = str(user_id).strip() if user_id else ""
        clean_doc_id = str(document_id).strip() if document_id else ""

        if not clean_user_id:
            raise ValueError("user_id is strictly required for document indexing into vector store")
        if not clean_doc_id:
            raise ValueError("document_id is strictly required for document indexing into vector store")

        if self.embedding_provider.dimension != self.expected_dimension:
            raise ValueError(
                f"Embedding provider dimension ({self.embedding_provider.dimension}) does not match "
                f"pgvector store dimension ({self.expected_dimension})."
            )

        texts = [chunk.text for chunk in chunks]
        titles = [str(chunk.document_name) for chunk in chunks]
        embeddings = self.embedding_provider.embed_texts(texts, titles=titles)

        for i, emb in enumerate(embeddings):
            if len(emb) != self.expected_dimension:
                raise ValueError(
                    f"Chunk embedding dimension {len(emb)} at index {i} does not match expected {self.expected_dimension}"
                )

        with SessionLocal() as db:
            # Delete any existing chunks for this specific document and user
            db.query(DocumentChunkModel).filter(
                DocumentChunkModel.owner_user_id == clean_user_id,
                DocumentChunkModel.document_id == clean_doc_id,
            ).delete()

            records = [
                DocumentChunkModel(
                    id=str(uuid.uuid4()),
                    chunk_id=str(chunk.id),
                    document_id=clean_doc_id,
                    owner_user_id=clean_user_id,
                    document_name=str(chunk.document_name),
                    page_number=int(chunk.page_number),
                    chunk_index=int(chunk.chunk_index),
                    text=chunk.text,
                    file_size_bytes=int(file_size_bytes),
                    embedding=embeddings[i] if i < len(embeddings) else None,
                )
                for i, chunk in enumerate(chunks)
            ]
            db.add_all(records)
            db.commit()

        logger.info(
            "pgvector indexing: user_id=%s, document_id=%s, chunks_count=%d",
            clean_user_id,
            clean_doc_id,
            len(chunks),
        )

    def similarity_search(
        self,
        query: str,
        user_id: str,
        top_k: int = 4,
        document_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve most relevant chunks using cosine similarity.
        STRICT SECURITY RULE: user_id is mandatory. No cross-tenant data leakage permitted.
        """
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id:
            raise ValueError("user_id is strictly required for similarity search to maintain data isolation")

        query_embedding = self.embedding_provider.embed_query(query)
        if len(query_embedding) != self.expected_dimension:
            raise ValueError(
                f"Query embedding dimension {len(query_embedding)} does not match "
                f"pgvector store dimension {self.expected_dimension}."
            )

        clean_filter = str(document_filter).strip() if document_filter else None

        with SessionLocal() as db:
            dialect_name = db.bind.dialect.name if db.bind else "postgresql"

            if dialect_name == "postgresql":
                # Native PostgreSQL pgvector cosine distance: embedding <=> :query_vec
                vec_str = "[" + ",".join(f"{float(x):.8f}" for x in query_embedding) + "]"
                query_sql = """
                    SELECT
                        id,
                        chunk_id,
                        document_id,
                        owner_user_id,
                        document_name,
                        page_number,
                        chunk_index,
                        text,
                        file_size_bytes,
                        (embedding <=> CAST(:query_vec AS vector)) AS distance
                    FROM document_chunks
                    WHERE owner_user_id = :user_id
                """
                params: Dict[str, Any] = {
                    "query_vec": vec_str,
                    "user_id": clean_user_id,
                    "top_k": top_k,
                }
                if clean_filter:
                    query_sql += " AND document_name = :doc_filter"
                    params["doc_filter"] = clean_filter

                query_sql += " ORDER BY distance ASC LIMIT :top_k"
                rows = db.execute(text(query_sql), params).mappings().all()

                retrieved: List[Dict[str, Any]] = []
                for row in rows:
                    dist = float(row["distance"])
                    similarity = round(1.0 - dist, 4)
                    retrieved.append({
                        "text": row["text"],
                        "document_name": row["document_name"],
                        "source_filename": row["document_name"],
                        "document_id": row["document_id"],
                        "chunk_id": row["chunk_id"],
                        "user_id": row["owner_user_id"],
                        "page_number": int(row["page_number"]),
                        "chunk_index": int(row["chunk_index"]),
                        "similarity": similarity,
                        "distance": dist,
                    })

                logger.info(
                    "pgvector retrieval (PostgreSQL native): user_id=%s, retrieved_count=%d",
                    clean_user_id,
                    len(retrieved),
                )
                return retrieved

            else:
                # SQLite / non-PostgreSQL fallback (used for local offline unit tests)
                stmt = db.query(DocumentChunkModel).filter(
                    DocumentChunkModel.owner_user_id == clean_user_id
                )
                if clean_filter:
                    stmt = stmt.filter(DocumentChunkModel.document_name == clean_filter)

                chunks = stmt.all()
                if not chunks:
                    return []

                scored = []
                for chunk in chunks:
                    c_vec = chunk.embedding
                    if c_vec and len(c_vec) == len(query_embedding):
                        dist = _cosine_distance(query_embedding, c_vec)
                    else:
                        dist = 1.0
                    similarity = round(1.0 - dist, 4)
                    scored.append((dist, similarity, chunk))

                scored.sort(key=lambda x: x[0])
                top_results = scored[:top_k]

                retrieved = [
                    {
                        "text": chunk.text,
                        "document_name": chunk.document_name,
                        "source_filename": chunk.document_name,
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.chunk_id,
                        "user_id": chunk.owner_user_id,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                        "similarity": sim,
                        "distance": dist,
                    }
                    for dist, sim, chunk in top_results
                ]

                logger.info(
                    "pgvector retrieval (fallback): user_id=%s, retrieved_count=%d",
                    clean_user_id,
                    len(retrieved),
                )
                return retrieved

    def list_documents(self, user_id: str) -> List[DocumentSummary]:
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id:
            return []

        with SessionLocal() as db:
            chunks = (
                db.query(DocumentChunkModel)
                .filter(DocumentChunkModel.owner_user_id == clean_user_id)
                .order_by(DocumentChunkModel.created_at.desc())
                .all()
            )
            if not chunks:
                return []

            docs_map: Dict[str, Dict[str, Any]] = {}
            for c in chunks:
                key = c.document_id or c.document_name
                if key not in docs_map:
                    docs_map[key] = {
                        "id": c.document_id,
                        "document_name": c.document_name,
                        "owner_user_id": clean_user_id,
                        "pages": set(),
                        "total_chunks": 0,
                        "file_size_bytes": c.file_size_bytes,
                        "uploaded_at": c.created_at.isoformat() if c.created_at else datetime.now(timezone.utc).isoformat(),
                    }
                docs_map[key]["pages"].add(c.page_number)
                docs_map[key]["total_chunks"] += 1

            summaries = [
                DocumentSummary(
                    id=item["id"],
                    document_name=item["document_name"],
                    total_pages=len(item["pages"]),
                    total_chunks=item["total_chunks"],
                    file_size_bytes=item["file_size_bytes"],
                    uploaded_at=item["uploaded_at"],
                    owner_user_id=clean_user_id,
                )
                for item in docs_map.values()
            ]
            return sorted(summaries, key=lambda s: s.uploaded_at, reverse=True)

    def delete_document(self, user_id: str, document_identifier: str) -> bool:
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id or not document_identifier:
            return False
        clean_ident = str(document_identifier).strip()

        with SessionLocal() as db:
            deleted = (
                db.query(DocumentChunkModel)
                .filter(
                    DocumentChunkModel.owner_user_id == clean_user_id,
                    (DocumentChunkModel.document_name == clean_ident)
                    | (DocumentChunkModel.document_id == clean_ident),
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            return deleted > 0

    def clear_user_documents(self, user_id: str) -> int:
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id:
            return 0

        with SessionLocal() as db:
            deleted = (
                db.query(DocumentChunkModel)
                .filter(DocumentChunkModel.owner_user_id == clean_user_id)
                .delete(synchronize_session=False)
            )
            db.commit()
            logger.info("pgvector clear_user_documents: user_id=%s, deleted_chunks=%d", clean_user_id, deleted)
            return deleted

    def quarantine_legacy_chunks(self) -> int:
        with SessionLocal() as db:
            updated = (
                db.query(DocumentChunkModel)
                .filter(
                    (DocumentChunkModel.owner_user_id == None)  # noqa: E711
                    | (DocumentChunkModel.owner_user_id == "")
                    | (DocumentChunkModel.owner_user_id == "unknown")
                    | (DocumentChunkModel.owner_user_id == "None")
                )
                .update({"owner_user_id": "__legacy_quarantined__"}, synchronize_session=False)
            )
            db.commit()
            if updated:
                logger.info("Quarantined %d legacy chunks in pgvector", updated)
            return updated

    def reassign_quarantined_documents(
        self,
        target_user_id: str,
        document_name: Optional[str] = None,
    ) -> int:
        clean_target = str(target_user_id).strip()
        if not clean_target:
            raise ValueError("target_user_id is required")

        with SessionLocal() as db:
            q = db.query(DocumentChunkModel).filter(
                DocumentChunkModel.owner_user_id == "__legacy_quarantined__"
            )
            if document_name:
                q = q.filter(DocumentChunkModel.document_name == str(document_name).strip())
            updated = q.update({"owner_user_id": clean_target}, synchronize_session=False)
            db.commit()
            logger.info("Reassigned %d quarantined chunks to user_id=%s in pgvector", updated, clean_target)
            return updated
