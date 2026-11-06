import os
import threading
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from app.core.config import settings
from app.schemas.tutor import DocumentChunk, DocumentSummary

logger = logging.getLogger(__name__)

class VectorStoreService:
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

        # Chroma handles upserting by ID
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

        # Server-enforced ownership filter
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
            # In Chroma with cosine distance: distance = 1 - similarity.
            similarity = round(1.0 - float(dist), 4)
            retrieved.append({
                "text": doc_text,
                "document_name": meta.get("document_name", "Unknown"),
                "source_filename": meta.get("source_filename", meta.get("document_name", "Unknown")),
                "document_id": meta.get("document_id"),
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
        """
        Aggregate unique documents stored in ChromaDB belonging strictly to user_id.
        """
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
        """
        Delete all chunks belonging strictly to user_id for the given document name or ID.
        """
        clean_user_id = str(user_id).strip() if user_id else ""
        if not clean_user_id or not document_identifier:
            return False

        clean_ident = str(document_identifier).strip()

        # Check by document_name
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

        # Check by document_id
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
        """
        Delete all documents and chunks belonging strictly to user_id.
        NEVER wipes other users' data or the shared collection.
        """
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
        """
        Identify legacy chunks in ChromaDB without a verified user_id,
        and quarantine them by tagging with user_id='__legacy_quarantined__'.
        This renders them completely inaccessible to normal authenticated user queries.
        """
        all_records = self.collection.get(include=["metadatas", "documents"])
        if not all_records or not all_records.get("ids"):
            return 0

        quarantined_ids = []
        quarantined_metas = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for chunk_id, meta in zip(all_records["ids"], all_records["metadatas"]):
            user_id = meta.get("user_id") if meta else None
            # If no user_id or empty or already unassigned
            if not user_id or str(user_id).strip() in ("", "None", "unknown"):
                updated_meta = dict(meta) if meta else {}
                updated_meta["user_id"] = "__legacy_quarantined__"
                updated_meta["quarantined_at"] = now_iso
                quarantined_ids.append(chunk_id)
                quarantined_metas.append(updated_meta)

        if quarantined_ids:
            # Update metadatas in place
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
        """
        Safe recovery procedure: Reassign quarantined legacy chunks to a verified target user ID.
        """
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
