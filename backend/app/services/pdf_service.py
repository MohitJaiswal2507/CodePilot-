import io
import re
from typing import List, Tuple
import pypdf
from app.core.config import settings
from app.schemas.tutor import DocumentChunk

def validate_pdf(file_bytes: bytes, filename: str) -> None:
    """Validate uploaded file format, size, and PDF magic header."""
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Only PDF documents (.pdf) are supported.")
    
    if len(file_bytes) == 0:
        raise ValueError("The uploaded file is empty (0 bytes).")
    
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(
            f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_MB}MB "
            f"({len(file_bytes) / (1024 * 1024):.2f}MB uploaded)."
        )
    
    if not file_bytes.startswith(b"%PDF"):
        raise ValueError("Invalid PDF format: file lacks standard PDF header.")

def extract_text_by_page(file_bytes: bytes, filename: str) -> List[Tuple[int, str]]:
    """Extract clean text from each page of the PDF."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Corrupt or unreadable PDF file: {exc}")
    
    if reader.is_encrypted:
        try:
            # Try decrypting with empty password
            reader.decrypt("")
        except Exception:
            raise ValueError(f"Password-protected or encrypted PDFs are not supported: {filename}")

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError(f"PDF document contains 0 pages: {filename}")

    extracted_pages: List[Tuple[int, str]] = []
    total_text_length = 0

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        
        # Clean up null bytes and normalize whitespace
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        
        if cleaned:
            extracted_pages.append((page_num, cleaned))
            total_text_length += len(cleaned)

    if total_text_length < 20:
        raise ValueError(
            "PDF contains no extractable text. It may consist of scanned images or empty pages. "
            "Please upload a searchable text-based PDF."
        )

    return extracted_pages

def chunk_document(
    pages: List[Tuple[int, str]],
    document_name: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> List[DocumentChunk]:
    """
    Split extracted page text into coherent chunks with overlap,
    preserving exact page numbers and document metadata.
    """
    chunk_size = chunk_size or settings.DEFAULT_CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.DEFAULT_CHUNK_OVERLAP

    chunks: List[DocumentChunk] = []
    global_chunk_idx = 0
    clean_doc_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", document_name)

    for page_num, page_text in pages:
        # Split on sentence boundaries to keep semantics intact
        sentences = re.split(r"(?<=[.!?])\s+", page_text)
        current_chunk: List[str] = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # If a single sentence is longer than chunk_size, split by characters
            if len(sentence) > chunk_size:
                if current_chunk:
                    chunk_text = " ".join(current_chunk)
                    chunks.append(
                        DocumentChunk(
                            id=f"{clean_doc_name}_p{page_num}_c{global_chunk_idx}",
                            document_name=document_name,
                            page_number=page_num,
                            chunk_index=global_chunk_idx,
                            text=chunk_text,
                        )
                    )
                    global_chunk_idx += 1
                    current_chunk = []
                    current_length = 0

                # Slice oversized sentence
                start = 0
                while start < len(sentence):
                    end = min(start + chunk_size, len(sentence))
                    sub_text = sentence[start:end]
                    chunks.append(
                        DocumentChunk(
                            id=f"{clean_doc_name}_p{page_num}_c{global_chunk_idx}",
                            document_name=document_name,
                            page_number=page_num,
                            chunk_index=global_chunk_idx,
                            text=sub_text,
                        )
                    )
                    global_chunk_idx += 1
                    start += (chunk_size - chunk_overlap)
                continue

            if current_length + len(sentence) + 1 <= chunk_size:
                current_chunk.append(sentence)
                current_length += len(sentence) + 1
            else:
                chunk_text = " ".join(current_chunk)
                chunks.append(
                    DocumentChunk(
                        id=f"{clean_doc_name}_p{page_num}_c{global_chunk_idx}",
                        document_name=document_name,
                        page_number=page_num,
                        chunk_index=global_chunk_idx,
                        text=chunk_text,
                    )
                )
                global_chunk_idx += 1

                # Carry over overlap from previous sentences
                overlap_chunk: List[str] = []
                overlap_len = 0
                for prev in reversed(current_chunk):
                    if overlap_len + len(prev) + 1 <= chunk_overlap:
                        overlap_chunk.insert(0, prev)
                        overlap_len += len(prev) + 1
                    else:
                        break

                current_chunk = overlap_chunk + [sentence]
                current_length = sum(len(s) + 1 for s in current_chunk)

        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append(
                DocumentChunk(
                    id=f"{clean_doc_name}_p{page_num}_c{global_chunk_idx}",
                    document_name=document_name,
                    page_number=page_num,
                    chunk_index=global_chunk_idx,
                    text=chunk_text,
                )
            )
            global_chunk_idx += 1

    return chunks
