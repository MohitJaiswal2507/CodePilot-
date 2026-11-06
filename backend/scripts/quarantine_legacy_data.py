"""
Quarantine legacy ChromaDB chunks that do not have an authenticated owner_user_id.
Tags legacy chunks with user_id='__legacy_quarantined__'.
This ensures legacy unassigned chunks are NEVER returned in user similarity searches or document lists,
while preserving their data intact for recovery.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.vector_store import VectorStoreService

def run_quarantine():
    print("Initializing VectorStoreService...")
    vs = VectorStoreService.get_instance()
    total_count = vs.collection.count()
    print(f"Total chunks in collection: {total_count}")

    quarantined = vs.quarantine_legacy_chunks()
    print(f"Successfully quarantined {quarantined} legacy chunks.")

    # Verify that no unassigned chunks remain
    all_records = vs.collection.get(include=["metadatas"])
    user_ids = set(m.get("user_id") for m in all_records["metadatas"])
    print(f"Distinct user_ids in collection now: {user_ids}")

if __name__ == "__main__":
    run_quarantine()

