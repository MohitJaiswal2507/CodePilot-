"""
RAG Evaluation Dataset Validation, Deterministic Metrics, & Isolated Runner (Steps 2-3).
"""

import csv
import gc
import json
import logging
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.tutor import ChatMessage, QueryResponse
from app.services.llm_gateway import LLMGenerationResult, generate_text
from app.services.pdf_service import chunk_document
from app.services.rag_service import RAGTrace, answer_question_with_trace
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

DEFAULT_RAG_DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "rag_eval_dataset.json"
DEFAULT_RAG_RESULTS_DIR = Path(__file__).resolve().parent / "results"
EVAL_SYNTHETIC_USER_ID = "eval_synthetic_user"

_CITATION_TAG_RE = re.compile(
    r"\[(?:Document|Doc):\s*([^,\]]+?),\s*Page:\s*(\d+)\]",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# Evaluation Dataset Schemas & Validation
# -----------------------------------------------------------------------------

class CorpusPage(BaseModel):
    page_number: int = Field(..., ge=1)
    text: str = Field(..., min_length=1)


class CorpusDocument(BaseModel):
    document_name: str = Field(..., min_length=1)
    pages: List[CorpusPage] = Field(..., min_length=1)


class ExpectedPage(BaseModel):
    document_name: str = Field(..., min_length=1)
    page_number: int = Field(..., ge=1)


EvalCaseCategory = Literal[
    "answerable_direct",
    "conversational_followup",
    "ambiguous",
    "unanswerable",
]


class RAGEvalCase(BaseModel):
    id: str = Field(..., min_length=1)
    category: EvalCaseCategory
    question: str = Field(..., min_length=2)
    history: List[ChatMessage] = Field(default_factory=list)
    document_filter: Optional[str] = None
    top_k: int = Field(default=4, ge=1, le=20)
    answerable: bool
    expect_clarification: bool = False
    expected_documents: List[str] = Field(default_factory=list)
    expected_pages: List[ExpectedPage] = Field(default_factory=list)
    expected_chunk_ids: List[str] = Field(default_factory=list)
    expected_evidence_substrings: List[str] = Field(default_factory=list)
    expected_answer_concepts: List[str] = Field(default_factory=list)
    mock_rewrite_response: Optional[str] = None
    mock_llm_response: Optional[str] = None


class RAGEvalDataset(BaseModel):
    dataset_version: str = Field(..., min_length=1)
    description: Optional[str] = None
    documents: List[CorpusDocument] = Field(..., min_length=1)
    cases: List[RAGEvalCase] = Field(..., min_length=1)


def validate_rag_dataset(dataset: RAGEvalDataset) -> List[str]:
    """
    Validate structural and ground-truth consistency of a loaded RAGEvalDataset against
    its own synthetic corpus and `pdf_service.chunk_document()` chunk IDs.

    Returns a list of validation error messages (empty list indicates a valid dataset).
    """
    errors: List[str] = []

    seen_docs: set[str] = set()
    page_text_map: Dict[Tuple[str, int], str] = {}
    valid_chunk_ids: set[str] = set()
    chunk_text_map: Dict[str, str] = {}

    for doc in dataset.documents:
        doc_key = doc.document_name.strip().lower()
        if doc_key in seen_docs:
            errors.append(f"Duplicate corpus document_name: '{doc.document_name}'.")
        seen_docs.add(doc_key)

        seen_pages: set[int] = set()
        pages_tuples: List[Tuple[int, str]] = []
        for page in doc.pages:
            if page.page_number in seen_pages:
                errors.append(f"Duplicate page {page.page_number} in document '{doc.document_name}'.")
            seen_pages.add(page.page_number)
            page_text_map[(doc_key, page.page_number)] = page.text
            pages_tuples.append((page.page_number, page.text))

        chunks = chunk_document(pages_tuples, doc.document_name)
        for ch in chunks:
            valid_chunk_ids.add(ch.id)
            chunk_text_map[ch.id] = ch.text

    seen_case_ids: set[str] = set()
    for case in dataset.cases:
        if case.id in seen_case_ids:
            errors.append(f"Duplicate case id: '{case.id}'.")
        seen_case_ids.add(case.id)

        if case.expect_clarification and case.answerable:
            errors.append(f"Case '{case.id}': expect_clarification=True cannot also set answerable=True.")

        if case.answerable:
            if not (case.expected_documents or case.expected_pages or case.expected_chunk_ids):
                errors.append(f"Answerable case '{case.id}' must define ground-truth targets.")

            for d_name in case.expected_documents:
                if d_name.strip().lower() not in seen_docs:
                    errors.append(f"Case '{case.id}' references unknown expected_document '{d_name}'.")

            for ep in case.expected_pages:
                if (ep.document_name.strip().lower(), ep.page_number) not in page_text_map:
                    errors.append(
                        f"Case '{case.id}' references missing corpus page {ep.document_name}#p{ep.page_number}."
                    )

            for cid in case.expected_chunk_ids:
                if cid not in valid_chunk_ids:
                    errors.append(f"Case '{case.id}' references unknown chunk_id '{cid}'.")

            # Verify every expected_evidence_substring exists in at least one target page/chunk
            candidate_texts: List[str] = []
            for cid in case.expected_chunk_ids:
                if cid in chunk_text_map:
                    candidate_texts.append(chunk_text_map[cid])
            for ep in case.expected_pages:
                txt = page_text_map.get((ep.document_name.strip().lower(), ep.page_number))
                if txt:
                    candidate_texts.append(txt)
            combined_target_text = " ".join(candidate_texts).lower()
            for sub in case.expected_evidence_substrings:
                if sub.lower() not in combined_target_text:
                    errors.append(
                        f"Case '{case.id}' evidence substring '{sub}' not found in ground-truth corpus text."
                    )
        else:
            if case.expected_documents or case.expected_pages or case.expected_chunk_ids:
                errors.append(
                    f"Non-answerable case '{case.id}' must not define expected retrieval targets."
                )

    return errors


def load_rag_dataset(path: Optional[Path] = None) -> RAGEvalDataset:
    """Load and strictly validate a RAG evaluation dataset from JSON."""
    dataset_path = Path(path) if path is not None else DEFAULT_RAG_DATASET_PATH
    raw_data = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset = RAGEvalDataset.model_validate(raw_data)
    errors = validate_rag_dataset(dataset)
    if errors:
        raise ValueError(f"Invalid RAG evaluation dataset ({dataset_path}): " + "; ".join(errors))
    return dataset


# -----------------------------------------------------------------------------
# Pure Retrieval Metric Functions
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class RetrievalCaseMetrics:
    case_id: str
    k: int
    retrieved_count: int
    relevant_retrieved_count: int
    matched_targets_count: int
    total_targets_count: int
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    top1_similarity: Optional[float]


def _chunk_dedup_key(chunk: Dict[str, Any]) -> Tuple[Any, ...]:
    cid = chunk.get("chunk_id")
    if isinstance(cid, str) and cid.strip():
        return ("chunk_id", cid.strip())
    doc = str(chunk.get("document_name", "")).strip().lower()
    page = int(chunk.get("page_number", 0) or 0)
    if chunk.get("chunk_index") is not None:
        return ("doc_page_idx", doc, page, int(chunk["chunk_index"]))
    return ("doc_page_text", doc, page, str(chunk.get("text", "")).strip())


def deduplicate_retrieved_chunks(retrieved_chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Preserve rank order while removing duplicate retrieved chunks."""
    seen: set[Tuple[Any, ...]] = set()
    unique: List[Dict[str, Any]] = []
    for chunk in retrieved_chunks:
        key = _chunk_dedup_key(chunk)
        if key not in seen:
            seen.add(key)
            unique.append(chunk)
    return unique


def _chunk_matches_evidence(chunk: Dict[str, Any], evidence_substrings: Sequence[str]) -> bool:
    if not evidence_substrings:
        return True
    text_low = str(chunk.get("text", "")).lower()
    return any(sub.lower() in text_low for sub in evidence_substrings)


def evaluate_retrieval_case(
    case: RAGEvalCase,
    retrieved_chunks: Sequence[Dict[str, Any]],
) -> RetrievalCaseMetrics:
    """
    Compute Precision@K, Recall@K, Reciprocal Rank, and Top-1 Similarity for one case.

    Anti-inflation safeguards:
    - Duplicate retrieved chunks are deduplicated before counting Precision@K.
    - Each distinct ground-truth target is counted at most once for Recall@K.
    - A single chunk cannot match multiple independent ground-truth targets to inflate Recall@K.
    """
    k = max(1, case.top_k)
    top_slice = list(retrieved_chunks[:k])
    top1_sim: Optional[float] = None
    if top_slice and top_slice[0].get("similarity") is not None:
        top1_sim = float(top_slice[0]["similarity"])

    unique_retrieved = deduplicate_retrieved_chunks(top_slice)

    # Non-answerable or clarification cases have no retrieval ground-truth targets
    if not case.answerable:
        return RetrievalCaseMetrics(
            case_id=case.id,
            k=k,
            retrieved_count=len(unique_retrieved),
            relevant_retrieved_count=0,
            matched_targets_count=0,
            total_targets_count=0,
            precision_at_k=0.0,
            recall_at_k=0.0,
            reciprocal_rank=0.0,
            top1_similarity=top1_sim,
        )

    # Determine canonical target set (preferring chunk IDs, then pages, then documents)
    if case.expected_chunk_ids:
        target_mode = "chunk_id"
        targets: set[Any] = set(case.expected_chunk_ids)
    elif case.expected_pages:
        target_mode = "page"
        targets = {(p.document_name.strip().lower(), p.page_number) for p in case.expected_pages}
    else:
        target_mode = "document"
        targets = {d.strip().lower() for d in case.expected_documents}

    relevant_count = 0
    matched_targets: set[Any] = set()
    first_relevant_rank: Optional[int] = None

    for rank_idx, chunk in enumerate(unique_retrieved, start=1):
        doc_low = str(chunk.get("document_name", "")).strip().lower()
        page_num = int(chunk.get("page_number", 0) or 0)
        chunk_id = chunk.get("chunk_id")
        is_relevant = False
        matched_target: Any = None

        if target_mode == "chunk_id":
            if isinstance(chunk_id, str) and chunk_id in targets:
                is_relevant = True
                matched_target = chunk_id
            elif chunk_id is None and case.expected_pages:
                # Fallback only when mock vector store omits chunk_id metadata
                page_targets = {(p.document_name.strip().lower(), p.page_number) for p in case.expected_pages}
                if (doc_low, page_num) in page_targets and _chunk_matches_evidence(
                    chunk, case.expected_evidence_substrings
                ):
                    is_relevant = True
                    # Map at most one unmatched target deterministically to prevent multi-target inflation
                    unmatched = sorted(t for t in targets if t not in matched_targets)
                    if unmatched:
                        matched_target = unmatched[0]
        elif target_mode == "page":
            pair = (doc_low, page_num)
            if pair in targets and _chunk_matches_evidence(chunk, case.expected_evidence_substrings):
                is_relevant = True
                matched_target = pair
        else:
            if doc_low in targets and _chunk_matches_evidence(chunk, case.expected_evidence_substrings):
                is_relevant = True
                matched_target = doc_low

        if is_relevant:
            relevant_count += 1
            if matched_target is not None:
                matched_targets.add(matched_target)
            if first_relevant_rank is None:
                first_relevant_rank = rank_idx

    total_targets = max(1, len(targets))
    precision_at_k = relevant_count / k
    recall_at_k = len(matched_targets) / total_targets
    reciprocal_rank = (1.0 / first_relevant_rank) if first_relevant_rank is not None else 0.0

    return RetrievalCaseMetrics(
        case_id=case.id,
        k=k,
        retrieved_count=len(unique_retrieved),
        relevant_retrieved_count=relevant_count,
        matched_targets_count=len(matched_targets),
        total_targets_count=len(targets),
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        reciprocal_rank=reciprocal_rank,
        top1_similarity=top1_sim,
    )


def mean_top1_similarity(case_metrics: Sequence[RetrievalCaseMetrics]) -> Optional[float]:
    """Compute average top-1 similarity across cases that retrieved at least one chunk."""
    sims = [m.top1_similarity for m in case_metrics if m.top1_similarity is not None]
    if not sims:
        return None
    return sum(sims) / len(sims)


# -----------------------------------------------------------------------------
# Pure Deterministic Answer & Citation Metric Functions
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class AnswerCaseMetrics:
    case_id: str
    is_error: bool
    correct_refusal: Optional[bool]
    false_refusal: Optional[bool]
    clarification_matched: Optional[bool]
    citation_present: Optional[bool]
    citations_grounded: bool
    hallucinated_citation_tags: int
    lexical_concept_coverage: Optional[float]


def extract_explicit_citation_tags(answer_text: str) -> List[Tuple[str, int]]:
    """Parse explicit `[Document: <name>, Page: <num>]` tags from generated answer text."""
    tags: List[Tuple[str, int]] = []
    for doc_name, page_str in _CITATION_TAG_RE.findall(answer_text or ""):
        try:
            tags.append((doc_name.strip().lower(), int(page_str.strip())))
        except ValueError:
            continue
    return tags


_LATEX_WRAPPER_RE = re.compile(
    r"\\(?:mathcal|mathrm|text|mathit|mathbf|operatorname)\{([^{}]*)\}"
)


def _normalize_lexical_text(text: str) -> str:
    """
    Normalize case, whitespace, inline code backticks, and common Big-O LaTeX
    formatting differences so heuristic lexical concept coverage tolerates
    notational formatting variants such as `$O(n \\log n)$` or `` `O(n log n)` ``.
    """
    norm = (text or "").lower()
    norm = norm.replace("$$", " ").replace("$", " ").replace("`", " ")
    norm = norm.replace("\\(", " ").replace("\\)", " ").replace("\\[", " ").replace("\\]", " ")
    norm = _LATEX_WRAPPER_RE.sub(r" \1 ", norm)
    norm = norm.replace("\\left(", "(").replace("\\right)", ")")
    norm = norm.replace("\\left[", "[").replace("\\right]", "]")
    norm = re.sub(r"\\(?:log|ln)(?![a-z])", lambda m: f" {m.group(0)[1:]} ", norm)
    norm = re.sub(r"\\(?:cdot|times|ast)\b", " ", norm)
    norm = re.sub(r"\\[,;:!]", " ", norm)
    norm = re.sub(r"(?<=[a-z0-9])\s*\*\s*(?=[a-z0-9])", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    norm = re.sub(r"\b(log|ln)\s*\(\s*([a-z0-9]+)\s*\)", r"\1 \2", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    norm = re.sub(r"\(\s+", "(", norm)
    norm = re.sub(r"\s+\)", ")", norm)
    norm = re.sub(r"\bo\s+\(", "o(", norm)
    return norm


def evaluate_answer_case(
    case: RAGEvalCase,
    response: QueryResponse,
    retrieved_chunks: Sequence[Dict[str, Any]],
    trace: Optional[RAGTrace] = None,
) -> AnswerCaseMetrics:
    """
    Evaluate deterministic refusal, clarification, citation validity/grounding,
    and lexical concept coverage for a single RAG response.
    """
    # Index retrieved chunks by (doc_lower, page_num) -> list of stripped chunk texts
    retrieved_by_page: Dict[Tuple[str, int], List[str]] = {}
    for chunk in retrieved_chunks:
        key = (str(chunk.get("document_name", "")).strip().lower(), int(chunk.get("page_number", 0) or 0))
        retrieved_by_page.setdefault(key, []).append(str(chunk.get("text", "")).strip())

    # 1. Refusal & clarification classification
    correct_refusal: Optional[bool] = None
    false_refusal: Optional[bool] = None
    clarification_matched: Optional[bool] = None

    if case.expect_clarification:
        clar_flag = trace.clarification_triggered if trace is not None else (
            bool(response.standalone_query and response.standalone_query.startswith("CLARIFY:"))
        )
        clarification_matched = bool(
            clar_flag and not response.insufficient_context and len(response.citations) == 0 and not response.is_error
        )
    elif case.answerable:
        false_refusal = bool(response.insufficient_context)
    else:
        correct_refusal = bool(
            response.insufficient_context and len(response.citations) == 0 and not response.is_error
        )

    # 2. Citation presence (applicable on non-refused, non-clarification answerable cases)
    citation_present: Optional[bool] = None
    if case.answerable and not case.expect_clarification and not response.is_error:
        citation_present = bool(not response.insufficient_context and len(response.citations) >= 1)

    # 3. Citation grounding validity (zero fabricated tags, zero ungrounded Citation objects)
    explicit_tags = extract_explicit_citation_tags(response.answer)
    hallucinated_tags = sum(1 for tag in explicit_tags if tag not in retrieved_by_page)

    returned_citations_valid = True
    if response.insufficient_context and len(response.citations) > 0:
        returned_citations_valid = False
    else:
        for cit in response.citations:
            key = (cit.document_name.strip().lower(), int(cit.page_number))
            texts_on_page = retrieved_by_page.get(key)
            if not texts_on_page:
                returned_citations_valid = False
                break
            clean_snippet = cit.snippet[:-3].strip() if cit.snippet.endswith("...") else cit.snippet.strip()
            if clean_snippet and not any(clean_snippet in full_txt for full_txt in texts_on_page):
                returned_citations_valid = False
                break

    citations_grounded = (hallucinated_tags == 0) and returned_citations_valid

    # 4. Heuristic lexical concept coverage (explicitly NOT semantic proof)
    lexical_concept_coverage: Optional[float] = None
    if case.expected_answer_concepts:
        normalized_concepts = [
            norm_c
            for concept in case.expected_answer_concepts
            if (norm_c := _normalize_lexical_text(concept))
        ]
        if normalized_concepts:
            ans_norm = _normalize_lexical_text(response.answer or "")
            hits = sum(1 for norm_c in normalized_concepts if norm_c in ans_norm)
            lexical_concept_coverage = hits / len(normalized_concepts)

    return AnswerCaseMetrics(
        case_id=case.id,
        is_error=bool(response.is_error),
        correct_refusal=correct_refusal,
        false_refusal=false_refusal,
        clarification_matched=clarification_matched,
        citation_present=citation_present,
        citations_grounded=citations_grounded,
        hallucinated_citation_tags=hallucinated_tags,
        lexical_concept_coverage=lexical_concept_coverage,
    )


# -----------------------------------------------------------------------------
# Pure Summary Aggregation
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class RAGEvalSummary:
    total_cases: int
    answerable_count: int
    unanswerable_count: int
    ambiguous_count: int
    precision_at_k: float
    recall_at_k: float
    mrr: float
    answerable_mean_top1_similarity: Optional[float]
    unanswerable_mean_top1_similarity: Optional[float]
    refusal_accuracy: Optional[float]
    false_refusal_rate: Optional[float]
    clarification_accuracy: Optional[float]
    citation_presence_rate: Optional[float]
    citation_grounding_validity_rate: float
    lexical_concept_coverage: Optional[float]


def _safe_mean(values: Sequence[float]) -> Optional[float]:
    return (sum(values) / len(values)) if values else None


def aggregate_rag_eval_metrics(
    cases: Sequence[RAGEvalCase],
    retrieval_metrics: Sequence[RetrievalCaseMetrics],
    answer_metrics: Sequence[AnswerCaseMetrics],
) -> RAGEvalSummary:
    """Aggregate per-case retrieval and deterministic answer metrics into a summary report."""
    if not (len(cases) == len(retrieval_metrics) == len(answer_metrics)):
        raise ValueError("cases, retrieval_metrics, and answer_metrics must have identical length.")

    ans_ret: List[RetrievalCaseMetrics] = []
    unans_ret: List[RetrievalCaseMetrics] = []
    ambiguous_count = 0

    for case, ret in zip(cases, retrieval_metrics):
        if case.expect_clarification:
            ambiguous_count += 1
        elif case.answerable:
            ans_ret.append(ret)
        else:
            unans_ret.append(ret)

    precision_at_k = _safe_mean([m.precision_at_k for m in ans_ret]) or 0.0
    recall_at_k = _safe_mean([m.recall_at_k for m in ans_ret]) or 0.0
    mrr = _safe_mean([m.reciprocal_rank for m in ans_ret]) or 0.0

    refusal_vals = [1.0 if a.correct_refusal else 0.0 for a in answer_metrics if a.correct_refusal is not None]
    false_refusal_vals = [1.0 if a.false_refusal else 0.0 for a in answer_metrics if a.false_refusal is not None]
    clar_vals = [1.0 if a.clarification_matched else 0.0 for a in answer_metrics if a.clarification_matched is not None]
    cit_pres_vals = [1.0 if a.citation_present else 0.0 for a in answer_metrics if a.citation_present is not None]
    grounding_vals = [1.0 if a.citations_grounded else 0.0 for a in answer_metrics]
    concept_vals = [a.lexical_concept_coverage for a in answer_metrics if a.lexical_concept_coverage is not None]

    return RAGEvalSummary(
        total_cases=len(cases),
        answerable_count=len(ans_ret),
        unanswerable_count=len(unans_ret),
        ambiguous_count=ambiguous_count,
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        mrr=mrr,
        answerable_mean_top1_similarity=mean_top1_similarity(ans_ret),
        unanswerable_mean_top1_similarity=mean_top1_similarity(unans_ret),
        refusal_accuracy=_safe_mean(refusal_vals),
        false_refusal_rate=_safe_mean(false_refusal_vals),
        clarification_accuracy=_safe_mean(clar_vals),
        citation_presence_rate=_safe_mean(cit_pres_vals),
        citation_grounding_validity_rate=_safe_mean(grounding_vals) or 0.0,
        lexical_concept_coverage=_safe_mean(concept_vals),
    )


# -----------------------------------------------------------------------------
# Step 3: Isolated Vector Indexing, Offline/Live Execution, Judge & Reports
# -----------------------------------------------------------------------------

EvalMode = Literal["offline", "live"]

_JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator grading a RAG AI Tutor response.
Evaluate ONLY based on the student question, the retrieved reference chunks, and the generated answer.
Output strictly valid JSON with exactly these fields:
{
  "faithfulness_score": <float between 0.0 and 1.0>,
  "relevance_score": <float between 0.0 and 1.0>,
  "reasoning": "<brief one-sentence justification>"
}
Scoring guide:
- faithfulness_score: 1.0 if every factual claim in the answer is strictly supported by the retrieved reference chunks; 0.0 if fabricated or contradicted.
- relevance_score: 1.0 if the answer directly and clearly addresses the student question; 0.0 if off-topic or unhelpful."""


def _load_cached_embedder(model_name: str) -> Any:
    """
    Load SentenceTransformer strictly from local cache (`local_files_only=True`).
    Fails fast with an actionable error instead of triggering silent network downloads.
    """
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name, local_files_only=True)
    except Exception as exc:
        raise RuntimeError(
            f"Embedding model '{model_name}' is not available in the local Hugging Face cache "
            "(local_files_only=True). Run online initialization once or inject a test embedder "
            f"for offline unit tests. Underlying error: {type(exc).__name__}"
        ) from exc


def _build_isolated_vector_store(
    dataset: RAGEvalDataset,
    persist_dir: str,
    embedder: Optional[Any] = None,
) -> VectorStoreService:
    """
    Instantiate a dedicated, isolated VectorStoreService bound to `persist_dir`
    (never calling `VectorStoreService.get_instance()`) and index the synthetic corpus.
    """
    store = VectorStoreService(persist_dir=persist_dir, model_name=settings.EMBEDDING_MODEL_NAME)
    if embedder is not None:
        store._embedder = embedder
    else:
        store._embedder = _load_cached_embedder(settings.EMBEDDING_MODEL_NAME)

    for idx, doc in enumerate(dataset.documents):
        pages = [(p.page_number, p.text) for p in doc.pages]
        chunks = chunk_document(pages, doc.document_name)
        store.add_document_chunks(
            chunks=chunks,
            user_id=EVAL_SYNTHETIC_USER_ID,
            document_id=f"eval_doc_{idx + 1}",
        )

    return store


def _cleanup_isolated_vector_store(store: Optional[VectorStoreService], tmp_dir: str) -> None:
    """Release ChromaDB SQLite locks cleanly and delete temporary evaluation directory."""
    if store is not None:
        try:
            client = getattr(store, "_client", None)
            if client is not None:
                system = getattr(client, "_system", None)
                if system is not None and hasattr(system, "stop"):
                    system.stop()
        except Exception as exc:
            logger.debug("Ignoring Chroma stop error during eval cleanup: %s", type(exc).__name__)
    gc.collect()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def aggregate_telemetry_summary(telemetries: Sequence[Optional[LLMGenerationResult]]) -> Dict[str, Any]:
    """
    Aggregate LLM gateway telemetry without inventing missing token counts.
    Token sums remain None when zero records reported token usage.
    """
    valid = [t for t in telemetries if t is not None]
    if not valid:
        return {
            "calls_recorded": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "calls_with_usage": 0,
            "prompt_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "thoughts_tokens": None,
            "mean_latency_ms": None,
            "mean_success_latency_ms": None,
            "mean_failure_latency_ms": None,
            "mean_attempt_latency_ms": None,
            "error_categories": {},
            "total_retries": 0,
            "fallback_count": 0,
            "models_used": [],
        }

    def _sum_optional(attr: str) -> Optional[int]:
        vals = [getattr(t, attr) for t in valid if getattr(t, attr) is not None]
        return sum(vals) if vals else None

    calls_with_usage = sum(
        1
        for t in valid
        if t.prompt_tokens is not None or t.output_tokens is not None or t.total_tokens is not None
    )

    successful = [t for t in valid if t.success]
    failed = [t for t in valid if not t.success]
    error_categories: Dict[str, int] = {}
    for t in failed:
        cat = t.error_category or "unknown_error"
        error_categories[cat] = error_categories.get(cat, 0) + 1

    attempt_vals = [t.attempt_latency_ms for t in valid if t.attempt_latency_ms is not None]
    return {
        "calls_recorded": len(valid),
        "successful_calls": len(successful),
        "failed_calls": len(failed),
        "calls_with_usage": calls_with_usage,
        "prompt_tokens": _sum_optional("prompt_tokens"),
        "output_tokens": _sum_optional("output_tokens"),
        "total_tokens": _sum_optional("total_tokens"),
        "thoughts_tokens": _sum_optional("thoughts_tokens"),
        "mean_latency_ms": round(sum(t.latency_ms for t in valid) / len(valid), 2),
        "mean_success_latency_ms": round(sum(t.latency_ms for t in successful) / len(successful), 2) if successful else None,
        "mean_failure_latency_ms": round(sum(t.latency_ms for t in failed) / len(failed), 2) if failed else None,
        "mean_attempt_latency_ms": round(sum(attempt_vals) / len(attempt_vals), 2) if attempt_vals else None,
        "error_categories": error_categories,
        "total_retries": sum(t.retries for t in valid),
        "fallback_count": sum(1 for t in valid if t.fallback_used),
        "models_used": sorted({t.model_used for t in valid if t.model_used}),
    }


def _serialize_telemetry(t: Optional[LLMGenerationResult]) -> Optional[Dict[str, Any]]:
    if t is None:
        return None
    attempt_count = (
        len(t.attempt_latencies_ms)
        if t.attempt_latencies_ms is not None
        else (1 + t.retries if t.attempt_latency_ms is not None else None)
    )
    return {
        "model_used": t.model_used,
        "model_version": t.model_version,
        "success": t.success,
        "error_category": t.error_category,
        "prompt_tokens": t.prompt_tokens,
        "output_tokens": t.output_tokens,
        "total_tokens": t.total_tokens,
        "thoughts_tokens": t.thoughts_tokens,
        "latency_ms": t.latency_ms,
        "attempt_latency_ms": t.attempt_latency_ms,
        "attempt_latencies_ms": t.attempt_latencies_ms,
        "attempt_count": attempt_count,
        "retries": t.retries,
        "fallback_used": t.fallback_used,
    }


def _clamp_score(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, num))


def _evaluate_with_judge(
    case: RAGEvalCase,
    response: QueryResponse,
    retrieved_chunks: Sequence[Dict[str, Any]],
    model: Optional[str] = None,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Optional Gemini-as-a-judge evaluator (live mode only).
    Scores answer faithfulness against retrieved chunks and relevance against question.
    """
    if not case.answerable or response.insufficient_context or response.is_error or not retrieved_chunks:
        return {
            "evaluated": False,
            "faithfulness_score": None,
            "relevance_score": None,
            "reasoning": None,
            "telemetry": None,
            "error": None,
        }

    context_lines = [
        f"[{c.get('document_name', 'Unknown')} p.{c.get('page_number', 1)}]: {str(c.get('text', '')).strip()}"
        for c in retrieved_chunks
    ]
    prompt = (
        f"STUDENT QUESTION:\n{case.question}\n\n"
        f"RETRIEVED REFERENCE CHUNKS:\n" + "\n".join(context_lines) + "\n\n"
        f"GENERATED ANSWER:\n{response.answer}\n\n"
        "Return JSON evaluation."
    )

    try:
        gw_result = generate_text(
            prompt=prompt,
            system_instruction=_JUDGE_SYSTEM_PROMPT,
            model=model,
            temperature=0.0,
            response_mime_type="application/json",
            feature="rag_eval_judge",
            client=client,
            allow_fallback=False,
        )
        raw_text = gw_result.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        parsed = json.loads(raw_text.strip())
        return {
            "evaluated": True,
            "faithfulness_score": _clamp_score(parsed.get("faithfulness_score")),
            "relevance_score": _clamp_score(parsed.get("relevance_score")),
            "reasoning": str(parsed.get("reasoning", "")).strip() or None,
            "telemetry": _serialize_telemetry(gw_result),
            "error": None,
        }
    except Exception as exc:
        failure_telemetry = getattr(exc, "telemetry_result", None)
        return {
            "evaluated": False,
            "faithfulness_score": None,
            "relevance_score": None,
            "reasoning": None,
            "telemetry": _serialize_telemetry(failure_telemetry)
            if isinstance(failure_telemetry, LLMGenerationResult)
            else None,
            "error": type(exc).__name__,
        }


def write_rag_eval_reports(
    report: Dict[str, Any],
    output_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """
    Persist timestamped JSON report and append a summary row to `rag_eval_summary.csv`.
    Returns `(json_path, csv_path)`.
    """
    target_dir = Path(output_dir) if output_dir is not None else DEFAULT_RAG_RESULTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = report["mode"]
    json_path = target_dir / f"rag_eval_{mode}_{ts_slug}.json"
    # Disambiguate if multiple runs occur within the same second
    counter = 1
    while json_path.exists():
        json_path = target_dir / f"rag_eval_{mode}_{ts_slug}_{counter}.json"
        counter += 1

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    csv_path = target_dir / "rag_eval_summary.csv"
    summary = report["summary"]
    tel = report.get("telemetry_summary") or {}
    judge = report.get("judge_summary") or {}

    row = {
        "timestamp": report["timestamp"],
        "dataset_version": report["dataset_version"],
        "mode": mode,
        "judge_enabled": report["judge_enabled"],
        "total_cases": summary["total_cases"],
        "precision_at_k": summary["precision_at_k"],
        "recall_at_k": summary["recall_at_k"],
        "mrr": summary["mrr"],
        "answerable_mean_top1_similarity": summary["answerable_mean_top1_similarity"],
        "unanswerable_mean_top1_similarity": summary["unanswerable_mean_top1_similarity"],
        "refusal_accuracy": summary["refusal_accuracy"],
        "false_refusal_rate": summary["false_refusal_rate"],
        "clarification_accuracy": summary["clarification_accuracy"],
        "citation_presence_rate": summary["citation_presence_rate"],
        "citation_grounding_validity_rate": summary["citation_grounding_validity_rate"],
        "lexical_concept_coverage": summary["lexical_concept_coverage"],
        "total_tokens": tel.get("total_tokens"),
        "mean_latency_ms": tel.get("mean_latency_ms"),
        "judge_mean_faithfulness": judge.get("mean_faithfulness"),
        "judge_mean_relevance": judge.get("mean_relevance"),
        "json_report_file": json_path.name,
    }

    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return json_path, csv_path


def select_eval_cases(
    cases: Sequence[RAGEvalCase],
    case_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[RAGEvalCase]:
    """
    Select evaluation cases by explicit IDs and/or prefix limit while validating inputs.
    """
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError(f"limit must be a positive integer >= 1 (got {limit!r}).")

    selected = list(cases)

    if case_ids is not None:
        cleaned_ids = [str(cid).strip() for cid in case_ids if str(cid).strip()]
        if not cleaned_ids:
            raise ValueError("Case selection cannot be empty; provide at least one valid case ID.")
        if len(cleaned_ids) != len(case_ids):
            raise ValueError("Case selection contains blank case ID entries.")

        seen: set[str] = set()
        duplicates: List[str] = []
        for cid in cleaned_ids:
            if cid in seen and cid not in duplicates:
                duplicates.append(cid)
            seen.add(cid)
        if duplicates:
            raise ValueError(f"Duplicate case ID(s) in selection: {', '.join(duplicates)}")

        by_id = {c.id: c for c in cases}
        unknown = [cid for cid in cleaned_ids if cid not in by_id]
        if unknown:
            raise ValueError(f"Unknown case ID(s): {', '.join(unknown)}")

        selected = [by_id[cid] for cid in cleaned_ids]

    if limit is not None:
        selected = selected[:limit]

    if not selected:
        raise ValueError("Case selection resolved to zero cases.")

    return selected


def run_rag_evaluation(
    mode: EvalMode = "offline",
    dataset_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    top_k: Optional[int] = None,
    use_judge: bool = False,
    model: Optional[str] = None,
    judge_model: Optional[str] = None,
    embedder: Optional[Any] = None,
    judge_client: Optional[Any] = None,
    write_artifacts: bool = True,
    case_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    save_answers: bool = False,
) -> Dict[str, Any]:
    """
    Execute the end-to-end RAG evaluation pipeline against an ephemeral ChromaDB store.

    - `offline`: Uses deterministic mock rewrite/LLM responses from the dataset (0 Gemini calls).
    - `live`: Uses real `llm_gateway` via `answer_question_with_trace`, plus optional `--judge`.
    """
    if mode not in ("offline", "live"):
        raise ValueError(f"Unsupported evaluation mode '{mode}'. Must be 'offline' or 'live'.")
    if use_judge and mode != "live":
        raise ValueError("--judge is only supported with --mode live.")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1 or top_k > 20):
        raise ValueError(f"--top-k must be an integer between 1 and 20 (got {top_k!r}).")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError(f"--limit must be a positive integer >= 1 (got {limit!r}).")
    if mode == "live" and not settings.GEMINI_API_KEY.strip():
        raise ValueError("GEMINI_API_KEY is required in backend/.env for --mode live evaluation.")

    dataset = load_rag_dataset(dataset_path)
    cases_to_run = select_eval_cases(dataset.cases, case_ids=case_ids, limit=limit)
    tmp_dir = tempfile.mkdtemp(prefix="codepilot_rag_eval_")
    eval_store: Optional[VectorStoreService] = None

    try:
        # Always index the FULL synthetic corpus even when evaluating a subset of cases
        eval_store = _build_isolated_vector_store(dataset=dataset, persist_dir=tmp_dir, embedder=embedder)

        eval_cases: List[RAGEvalCase] = []
        retrieval_results: List[RetrievalCaseMetrics] = []
        answer_results: List[AnswerCaseMetrics] = []
        case_reports: List[Dict[str, Any]] = []
        all_rag_telemetries: List[Optional[LLMGenerationResult]] = []
        judge_telemetries: List[Optional[LLMGenerationResult]] = []
        judge_faithfulness_scores: List[float] = []
        judge_relevance_scores: List[float] = []

        for raw_case in cases_to_run:
            effective_k = top_k if top_k is not None else raw_case.top_k
            case = raw_case.model_copy(update={"top_k": effective_k})
            eval_cases.append(case)

            if mode == "offline":
                mock_rewrite = (
                    (lambda _p, c=case: c.mock_rewrite_response or c.question)
                    if case.history
                    else None
                )
                mock_llm = lambda _p, c=case: (
                    c.mock_llm_response
                    or "I cannot find sufficient evidence in the uploaded learning materials to answer this question."
                )
                response, trace = answer_question_with_trace(
                    question=case.question,
                    user_id=EVAL_SYNTHETIC_USER_ID,
                    vector_store=eval_store,
                    document_filter=case.document_filter,
                    top_k=effective_k,
                    history=case.history,
                    llm_callable=mock_llm,
                    rewrite_callable=mock_rewrite,
                    model=model,
                )
            else:
                response, trace = answer_question_with_trace(
                    question=case.question,
                    user_id=EVAL_SYNTHETIC_USER_ID,
                    vector_store=eval_store,
                    document_filter=case.document_filter,
                    top_k=effective_k,
                    history=case.history,
                    llm_callable=None,
                    rewrite_callable=None,
                    model=model,
                )

            ret_m = evaluate_retrieval_case(case, trace.retrieved_chunks)
            ans_m = evaluate_answer_case(case, response, trace.retrieved_chunks, trace=trace)

            retrieval_results.append(ret_m)
            answer_results.append(ans_m)

            if mode == "live":
                all_rag_telemetries.append(trace.rewriter_telemetry)
                all_rag_telemetries.append(trace.generation_telemetry)

            case_entry: Dict[str, Any] = {
                "case_id": case.id,
                "category": case.category,
                "answerable": case.answerable,
                "expect_clarification": case.expect_clarification,
                "retrieved_chunks_count": response.retrieved_chunks_count,
                "max_similarity": trace.max_similarity,
                "threshold_triggered": trace.threshold_triggered,
                "clarification_triggered": trace.clarification_triggered,
                "insufficient_context": response.insufficient_context,
                "is_error": response.is_error,
                "retrieval": asdict(ret_m),
                "answer": asdict(ans_m),
            }

            if save_answers:
                case_entry["standalone_query"] = trace.standalone_query
                case_entry["generated_answer"] = response.answer

            if mode == "live":
                case_entry["telemetry"] = {
                    "rewriter": _serialize_telemetry(trace.rewriter_telemetry),
                    "generation": _serialize_telemetry(trace.generation_telemetry),
                }

            if use_judge:
                judge_res = _evaluate_with_judge(
                    case=case,
                    response=response,
                    retrieved_chunks=trace.retrieved_chunks,
                    model=judge_model or model,
                    client=judge_client,
                )
                case_entry["judge"] = judge_res
                if judge_res["evaluated"]:
                    if judge_res["faithfulness_score"] is not None:
                        judge_faithfulness_scores.append(judge_res["faithfulness_score"])
                    if judge_res["relevance_score"] is not None:
                        judge_relevance_scores.append(judge_res["relevance_score"])
                if judge_res.get("telemetry") and judge_res["telemetry"].get("model_used"):
                    t_raw = judge_res["telemetry"]
                    judge_telemetries.append(
                        LLMGenerationResult(
                            text="",
                            model_used=t_raw["model_used"],
                            model_version=t_raw.get("model_version"),
                            prompt_tokens=t_raw.get("prompt_tokens"),
                            output_tokens=t_raw.get("output_tokens"),
                            total_tokens=t_raw.get("total_tokens"),
                            thoughts_tokens=t_raw.get("thoughts_tokens"),
                            latency_ms=t_raw.get("latency_ms", 0.0),
                            attempt_latency_ms=t_raw.get("attempt_latency_ms"),
                            attempt_latencies_ms=t_raw.get("attempt_latencies_ms"),
                            retries=t_raw.get("retries", 0),
                            fallback_used=t_raw.get("fallback_used", False),
                            success=t_raw.get("success", True),
                            error_category=t_raw.get("error_category"),
                        )
                    )

            case_reports.append(case_entry)

        summary = aggregate_rag_eval_metrics(eval_cases, retrieval_results, answer_results)
        telemetry_summary = aggregate_telemetry_summary(all_rag_telemetries) if mode == "live" else None

        judge_summary: Optional[Dict[str, Any]] = None
        if use_judge:
            judge_summary = {
                "evaluated_cases": len(judge_faithfulness_scores),
                "mean_faithfulness": _safe_mean(judge_faithfulness_scores),
                "mean_relevance": _safe_mean(judge_relevance_scores),
                "telemetry": aggregate_telemetry_summary(judge_telemetries),
            }

        report: Dict[str, Any] = {
            "dataset_version": dataset.dataset_version,
            "mode": mode,
            "judge_enabled": use_judge,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "top_k_override": top_k,
                "limit": limit,
                "selected_case_ids": [c.id for c in eval_cases],
                "save_answers": bool(save_answers),
                "similarity_threshold": settings.SIMILARITY_THRESHOLD,
                "embedding_model": settings.EMBEDDING_MODEL_NAME,
            },
            "summary": asdict(summary),
            "telemetry_summary": telemetry_summary,
            "judge_summary": judge_summary,
            "cases": case_reports,
        }

        if write_artifacts:
            json_path, csv_path = write_rag_eval_reports(report, output_dir=output_dir)
            report["artifacts"] = {
                "json_report": str(json_path),
                "csv_summary": str(csv_path),
            }

        return report
    finally:
        _cleanup_isolated_vector_store(eval_store, tmp_dir)


