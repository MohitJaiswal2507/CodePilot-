import pytest

from app.schemas.tutor import Citation, QueryResponse
from app.services.rag_service import RAGTrace
from evals.rag_evaluator import (
    DEFAULT_RAG_DATASET_PATH,
    RAGEvalCase,
    aggregate_rag_eval_metrics,
    deduplicate_retrieved_chunks,
    evaluate_answer_case,
    evaluate_retrieval_case,
    load_rag_dataset,
    mean_top1_similarity,
    validate_rag_dataset,
)


# ==============================================================================
# 1. CURATED DATASET LOADING & CONSISTENCY TESTS
# ==============================================================================

def test_curated_rag_eval_dataset_valid_and_complete():
    dataset = load_rag_dataset(DEFAULT_RAG_DATASET_PATH)
    assert dataset.dataset_version == "1.0"
    assert len(dataset.documents) == 5
    assert len(dataset.cases) == 20

    categories = {c.category for c in dataset.cases}
    assert categories == {"answerable_direct", "conversational_followup", "ambiguous", "unanswerable"}

    # Ensure unanswerable topics are genuinely absent from synthetic corpus text
    full_corpus_text = " ".join(
        page.text.lower() for doc in dataset.documents for page in doc.pages
    )
    for forbidden_term in ("kubernetes", "horizontalpodautoscaler", "shor", "tokio", "etcd", "raft"):
        assert forbidden_term not in full_corpus_text


def test_validate_rag_dataset_rejects_broken_ground_truth():
    dataset = load_rag_dataset(DEFAULT_RAG_DATASET_PATH)

    broken = dataset.model_copy(deep=True)
    broken.cases[0].expected_chunk_ids = ["non_existent_chunk_999"]
    errors = validate_rag_dataset(broken)
    assert any("non_existent_chunk_999" in e for e in errors)

    broken_evidence = dataset.model_copy(deep=True)
    broken_evidence.cases[0].expected_evidence_substrings = ["completely absent text xyz"]
    errors_ev = validate_rag_dataset(broken_evidence)
    assert any("completely absent text xyz" in e for e in errors_ev)

    broken_unans = dataset.model_copy(deep=True)
    unans_case = next(c for c in broken_unans.cases if not c.answerable and not c.expect_clarification)
    unans_case.expected_documents = ["dsa_algorithms.pdf"]
    errors_unans = validate_rag_dataset(broken_unans)
    assert any("must not define expected retrieval targets" in e for e in errors_unans)


# ==============================================================================
# 2. RETRIEVAL METRICS & ANTI-INFLATION TESTS
# ==============================================================================

def test_retrieval_metrics_exact_math_and_duplicate_prevention():
    case = RAGEvalCase(
        id="t_ret_1",
        category="answerable_direct",
        question="Explain merge sort and binary search",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0", "dsa_algorithms_pdf_p2_c1"],
    )

    retrieved = [
        {
            "chunk_id": "dsa_algorithms_pdf_p9_c9",
            "document_name": "other.pdf",
            "page_number": 9,
            "chunk_index": 9,
            "text": "Distractor",
            "similarity": 0.90,
        },
        {
            "chunk_id": "dsa_algorithms_pdf_p1_c0",
            "document_name": "dsa_algorithms.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Merge sort...",
            "similarity": 0.85,
        },
        {
            # Duplicate of rank 2 — must NOT inflate Precision@4 or Recall@4
            "chunk_id": "dsa_algorithms_pdf_p1_c0",
            "document_name": "dsa_algorithms.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Merge sort...",
            "similarity": 0.85,
        },
        {
            "chunk_id": "dsa_algorithms_pdf_p2_c1",
            "document_name": "dsa_algorithms.pdf",
            "page_number": 2,
            "chunk_index": 1,
            "text": "Binary search...",
            "similarity": 0.80,
        },
    ]

    unique = deduplicate_retrieved_chunks(retrieved)
    assert len(unique) == 3

    m = evaluate_retrieval_case(case, retrieved)
    assert m.relevant_retrieved_count == 2
    assert m.matched_targets_count == 2
    assert m.precision_at_k == pytest.approx(2 / 4)
    assert m.recall_at_k == pytest.approx(1.0)
    # First relevant chunk is at 1-based rank 2
    assert m.reciprocal_rank == pytest.approx(0.5)
    assert m.top1_similarity == pytest.approx(0.90)


def test_retrieval_metrics_avoid_page_and_one_to_many_inflation():
    # Two chunks on the same expected page should count toward only 1 page target
    page_case = RAGEvalCase(
        id="t_page_dedup",
        category="answerable_direct",
        question="Explain paging and deadlock",
        top_k=4,
        answerable=True,
        expected_pages=[
            {"document_name": "os.pdf", "page_number": 1},
            {"document_name": "os.pdf", "page_number": 2},
        ],
    )
    retrieved_same_page = [
        {"chunk_id": "os_p1_c0", "document_name": "os.pdf", "page_number": 1, "text": "a", "similarity": 0.88},
        {"chunk_id": "os_p1_c1", "document_name": "os.pdf", "page_number": 1, "text": "b", "similarity": 0.82},
    ]
    m_page = evaluate_retrieval_case(page_case, retrieved_same_page)
    assert m_page.matched_targets_count == 1
    assert m_page.recall_at_k == pytest.approx(0.5)

    # One mock chunk missing chunk_id cannot satisfy two chunk_id targets
    chunk_case = RAGEvalCase(
        id="t_chunk_no_id",
        category="answerable_direct",
        question="Test",
        top_k=4,
        answerable=True,
        expected_pages=[{"document_name": "os.pdf", "page_number": 1}],
        expected_chunk_ids=["os_p1_c0", "os_p1_c1"],
    )
    m_single = evaluate_retrieval_case(
        chunk_case,
        [{"document_name": "os.pdf", "page_number": 1, "text": "snippet", "similarity": 0.77}],
    )
    assert m_single.matched_targets_count == 1
    assert m_single.recall_at_k == pytest.approx(0.5)


def test_retrieval_metrics_handle_empty_results_safely():
    case = RAGEvalCase(
        id="t_empty",
        category="answerable_direct",
        question="Empty test",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
    )
    m = evaluate_retrieval_case(case, [])
    assert m.precision_at_k == 0.0
    assert m.recall_at_k == 0.0
    assert m.reciprocal_rank == 0.0
    assert m.top1_similarity is None
    assert mean_top1_similarity([m]) is None


# ==============================================================================
# 3. ANSWER, REFUSAL, CLARIFICATION & CITATION GROUNDING TESTS
# ==============================================================================

def test_answer_metrics_citation_grounding_and_hallucination_detection():
    case = RAGEvalCase(
        id="t_ans_cit",
        category="answerable_direct",
        question="What is merge sort complexity?",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_answer_concepts=["O(n log n)", "O(n)"],
    )
    retrieved = [
        {
            "chunk_id": "dsa_algorithms_pdf_p1_c0",
            "document_name": "dsa_algorithms.pdf",
            "page_number": 1,
            "text": "Merge sort runs in O(n log n) time and O(n) auxiliary space.",
            "similarity": 0.91,
        }
    ]

    valid_resp = QueryResponse(
        answer="Merge sort takes O(n log n) time and O(n) space [Document: dsa_algorithms.pdf, Page: 1].",
        citations=[
            Citation(
                document_name="dsa_algorithms.pdf",
                page_number=1,
                snippet="Merge sort runs in O(n log n) time",
            )
        ],
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    m_valid = evaluate_answer_case(case, valid_resp, retrieved)
    assert m_valid.citation_present is True
    assert m_valid.citations_grounded is True
    assert m_valid.hallucinated_citation_tags == 0
    assert m_valid.false_refusal is False
    assert m_valid.lexical_concept_coverage == pytest.approx(1.0)

    # Hallucinated page 99 tag in answer must fail citation grounding
    bad_tag_resp = QueryResponse(
        answer="Merge sort takes O(n log n) [Document: dsa_algorithms.pdf, Page: 99].",
        citations=valid_resp.citations,
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    m_bad_tag = evaluate_answer_case(case, bad_tag_resp, retrieved)
    assert m_bad_tag.hallucinated_citation_tags == 1
    assert m_bad_tag.citations_grounded is False

    # Fabricated snippet in Citation object must fail grounding
    bad_cit_resp = QueryResponse(
        answer="Merge sort takes O(n log n).",
        citations=[
            Citation(
                document_name="dsa_algorithms.pdf",
                page_number=1,
                snippet="Completely invented sentence not in chunk.",
            )
        ],
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    m_bad_cit = evaluate_answer_case(case, bad_cit_resp, retrieved)
    assert m_bad_cit.citations_grounded is False


def test_answer_metrics_refusal_clarification_and_aggregation():
    ans_case = RAGEvalCase(
        id="c1",
        category="answerable_direct",
        question="What is binary search complexity?",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p2_c1"],
        expected_answer_concepts=["O(log n)"],
    )
    unans_case = RAGEvalCase(
        id="c2",
        category="unanswerable",
        question="What is Kubernetes HPA?",
        answerable=False,
    )
    amb_case = RAGEvalCase(
        id="c3",
        category="ambiguous",
        question="What is its space complexity?",
        answerable=False,
        expect_clarification=True,
    )

    ret_1 = evaluate_retrieval_case(
        ans_case,
        [{"chunk_id": "dsa_algorithms_pdf_p2_c1", "document_name": "dsa_algorithms.pdf", "page_number": 2, "text": "O(log n)", "similarity": 0.89}],
    )
    ret_2 = evaluate_retrieval_case(
        unans_case,
        [{"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "Merge sort", "similarity": 0.14}],
    )
    ret_3 = evaluate_retrieval_case(amb_case, [])

    ans_1 = evaluate_answer_case(
        ans_case,
        QueryResponse(
            answer="Binary search takes O(log n) [Document: dsa_algorithms.pdf, Page: 2].",
            citations=[Citation(document_name="dsa_algorithms.pdf", page_number=2, snippet="O(log n)")],
            insufficient_context=False,
            retrieved_chunks_count=1,
        ),
        [{"document_name": "dsa_algorithms.pdf", "page_number": 2, "text": "O(log n)"}],
    )
    ans_2 = evaluate_answer_case(
        unans_case,
        QueryResponse(
            answer="I cannot find sufficient evidence in the uploaded learning materials.",
            citations=[],
            insufficient_context=True,
            retrieved_chunks_count=1,
        ),
        [],
    )
    ans_3 = evaluate_answer_case(
        amb_case,
        QueryResponse(
            answer="Could you clarify which algorithm you mean?",
            citations=[],
            insufficient_context=False,
            retrieved_chunks_count=0,
            standalone_query="CLARIFY: Could you clarify which algorithm you mean?",
        ),
        [],
        trace=RAGTrace(
            standalone_query="CLARIFY: Could you clarify which algorithm you mean?",
            clarification_triggered=True,
        ),
    )

    summary = aggregate_rag_eval_metrics(
        [ans_case, unans_case, amb_case],
        [ret_1, ret_2, ret_3],
        [ans_1, ans_2, ans_3],
    )

    assert summary.total_cases == 3
    assert summary.answerable_count == 1
    assert summary.unanswerable_count == 1
    assert summary.ambiguous_count == 1
    assert summary.precision_at_k == pytest.approx(0.25)
    assert summary.recall_at_k == pytest.approx(1.0)
    assert summary.mrr == pytest.approx(1.0)
    assert summary.answerable_mean_top1_similarity == pytest.approx(0.89)
    assert summary.unanswerable_mean_top1_similarity == pytest.approx(0.14)
    assert summary.refusal_accuracy == pytest.approx(1.0)
    assert summary.false_refusal_rate == pytest.approx(0.0)
    assert summary.clarification_accuracy == pytest.approx(1.0)
    assert summary.citation_presence_rate == pytest.approx(1.0)
    assert summary.citation_grounding_validity_rate == pytest.approx(1.0)
    assert summary.lexical_concept_coverage == pytest.approx(1.0)

