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


def test_rag_ans_01_expected_concepts_aligned_with_question():
    dataset = load_rag_dataset()
    case_map = {c.id: c for c in dataset.cases}
    rag_ans_01 = case_map["rag_ans_01"]
    assert rag_ans_01.expected_answer_concepts == ["O(n log n)", "O(n)"]


def test_lexical_concept_coverage_tolerates_latex_and_whitespace_variants():
    case = RAGEvalCase(
        id="latex_bigo_check",
        category="answerable_direct",
        question="Compare merge sort and binary search complexity.",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
        expected_answer_concepts=["O(n log n)", "O(n)", "O(log n)", "O(1)"],
    )
    retrieved = [
        {"document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "Merge sort O(n log n) and O(n)."}
    ]

    latex_resp = QueryResponse(
        answer=(
            "Merge sort runs in $O(n \\log n)$ time with `O( n )` space, "
            "whereas iterative binary search takes \\(O(\\log n)\\) time and $$\\mathcal{O}(1)$$ space "
            "[Document: dsa_algorithms.pdf, Page: 1]."
        ),
        citations=[],
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    metrics = evaluate_answer_case(case, latex_resp, retrieved)
    assert metrics.lexical_concept_coverage == pytest.approx(1.0)

    # Verify partial / missing concepts still reduce score accurately
    partial_resp = QueryResponse(
        answer="Merge sort runs in $O(n \\cdot \\log n)$ time [Document: dsa_algorithms.pdf, Page: 1].",
        citations=[],
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    partial_metrics = evaluate_answer_case(case, partial_resp, retrieved)
    assert partial_metrics.lexical_concept_coverage == pytest.approx(0.25)


def test_lexical_concept_coverage_log_parens_and_empty_concepts():
    from evals.rag_evaluator import _normalize_lexical_text

    assert _normalize_lexical_text("O(n log(n))") == "o(n log n)"
    assert _normalize_lexical_text(r"O(n \log(n) )") == "o(n log n)"
    assert _normalize_lexical_text(r"$O(n \log n)$") == "o(n log n)"

    # Only empty/whitespace concepts -> None (never counts as a trivial match)
    empty_concepts_case = RAGEvalCase(
        id="empty_concepts_check",
        category="answerable_direct",
        question="Sample question?",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
        expected_answer_concepts=["", "   "],
    )
    retrieved = [{"document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "Merge sort O(n log n)."}]
    empty_ans = QueryResponse(answer="", citations=[], insufficient_context=False, retrieved_chunks_count=1)
    assert evaluate_answer_case(empty_concepts_case, empty_ans, retrieved).lexical_concept_coverage is None

    # Mixed blank and real concepts: blank entries are ignored in denominator and numerator
    mixed_case = RAGEvalCase(
        id="mixed_concepts_check",
        category="answerable_direct",
        question="What is merge sort time complexity?",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
        expected_answer_concepts=["O(n log n)", "   ", ""],
    )
    log_paren_resp = QueryResponse(
        answer=r"Merge sort takes $O(n \log(n) )$ time [Document: dsa_algorithms.pdf, Page: 1].",
        citations=[],
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    assert evaluate_answer_case(mixed_case, log_paren_resp, retrieved).lexical_concept_coverage == pytest.approx(1.0)
    assert evaluate_answer_case(mixed_case, empty_ans, retrieved).lexical_concept_coverage == pytest.approx(0.0)


def test_failed_generation_excluded_from_quality_denominators_and_not_counted_as_refusal():
    ans_ok = RAGEvalCase(
        id="c_ok",
        category="answerable_direct",
        question="What is merge sort complexity?",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
        expected_answer_concepts=["O(n log n)", "O(n)"],
    )
    ans_err = RAGEvalCase(
        id="c_err",
        category="conversational_followup",
        question="How do closures work?",
        answerable=True,
        expected_documents=["programming_fundamentals.pdf"],
        expected_chunk_ids=["programming_fundamentals_pdf_p1_c0"],
        expected_answer_concepts=["lexical environment"],
    )
    unans_ok = RAGEvalCase(
        id="c_unans_ok",
        category="unanswerable",
        question="Explain Kubernetes HPA?",
        answerable=False,
    )
    unans_err = RAGEvalCase(
        id="c_unans_err",
        category="unanswerable",
        question="Explain etcd Raft?",
        answerable=False,
    )

    chunks_ok = [{"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "O(n log n) O(n)", "similarity": 0.85}]
    chunks_err = [{"chunk_id": "programming_fundamentals_pdf_p1_c0", "document_name": "programming_fundamentals.pdf", "page_number": 1, "text": "lexical environment", "similarity": 0.78}]
    chunks_unans = [{"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "O(n log n)", "similarity": 0.12}]

    r_ok = evaluate_retrieval_case(ans_ok, chunks_ok)
    r_err = evaluate_retrieval_case(ans_err, chunks_err)
    r_u_ok = evaluate_retrieval_case(unans_ok, chunks_unans)
    r_u_err = evaluate_retrieval_case(unans_err, [{"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "O(n log n)", "similarity": 0.40}])

    a_ok = evaluate_answer_case(
        ans_ok,
        QueryResponse(
            answer="O(n log n) and O(n) [Document: dsa_algorithms.pdf, Page: 1].",
            citations=[Citation(document_name="dsa_algorithms.pdf", page_number=1, snippet="O(n log n)")],
            insufficient_context=False,
            retrieved_chunks_count=1,
        ),
        chunks_ok,
        trace=RAGTrace(standalone_query="q1", retrieved_chunks=chunks_ok, max_similarity=0.85),
    )
    # Even if error response attaches fallback citations and zero matching concepts, it must be excluded
    a_err = evaluate_answer_case(
        ans_err,
        QueryResponse(
            answer="Error communicating with AI model: timed out.",
            citations=[Citation(document_name="programming_fundamentals.pdf", page_number=1, snippet="lexical environment")],
            insufficient_context=False,
            retrieved_chunks_count=1,
            is_error=True,
        ),
        chunks_err,
        trace=RAGTrace(standalone_query="q2", retrieved_chunks=chunks_err, max_similarity=0.78),
    )
    a_u_ok = evaluate_answer_case(
        unans_ok,
        QueryResponse(
            answer="I cannot find sufficient evidence.",
            citations=[],
            insufficient_context=True,
            retrieved_chunks_count=1,
        ),
        chunks_unans,
        trace=RAGTrace(standalone_query="u1", retrieved_chunks=chunks_unans, max_similarity=0.12, threshold_triggered=True),
    )
    a_u_err = evaluate_answer_case(
        unans_err,
        QueryResponse(
            answer="Error communicating with AI model: timed out.",
            citations=[],
            insufficient_context=True,  # even if flagged insufficient, is_error=True cannot count as refusal pass!
            retrieved_chunks_count=1,
            is_error=True,
        ),
        chunks_unans,
        trace=RAGTrace(standalone_query="u2", retrieved_chunks=chunks_unans, max_similarity=0.40, threshold_triggered=False),
    )

    assert a_err.lexical_concept_coverage is None
    assert a_err.citations_grounded is None
    assert a_err.false_refusal is None
    assert a_u_err.correct_refusal is None
    assert r_err.recall_at_k == pytest.approx(1.0)
    assert r_err.reciprocal_rank == pytest.approx(1.0)

    summary = aggregate_rag_eval_metrics(
        [ans_ok, ans_err, unans_ok, unans_err],
        [r_ok, r_err, r_u_ok, r_u_err],
        [a_ok, a_err, a_u_ok, a_u_err],
    )
    assert summary.error_count == 2
    # Generation expected on c_ok, c_err, c_unans_err (c_unans_ok triggered threshold gate)
    assert summary.error_rate == pytest.approx(2 / 3)
    assert summary.lexical_concept_coverage == pytest.approx(1.0)
    assert summary.citation_grounding_validity_rate == pytest.approx(1.0)
    assert summary.citation_presence_rate == pytest.approx(1.0)
    assert summary.explicit_citation_rate == pytest.approx(1.0)
    assert summary.false_refusal_rate == pytest.approx(0.0)
    assert summary.refusal_accuracy == pytest.approx(1.0)
    assert summary.recall_at_k == pytest.approx(1.0)


def test_failed_only_and_empty_denominators_return_none_safely():
    ans_case = RAGEvalCase(
        id="only_fail",
        category="answerable_direct",
        question="What is merge sort complexity?",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
        expected_answer_concepts=["O(n log n)"],
    )
    chunks = [{"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "O(n log n)", "similarity": 0.72}]
    ret = evaluate_retrieval_case(ans_case, chunks)
    ans = evaluate_answer_case(
        ans_case,
        QueryResponse(answer="Error communicating with AI model: timeout.", citations=[], is_error=True, retrieved_chunks_count=1),
        chunks,
        trace=RAGTrace(standalone_query="What is merge sort complexity?", retrieved_chunks=chunks, max_similarity=0.72),
    )
    failed_summary = aggregate_rag_eval_metrics([ans_case], [ret], [ans])
    assert failed_summary.error_count == 1
    assert failed_summary.error_rate == pytest.approx(1.0)
    assert failed_summary.recall_at_k == pytest.approx(1.0)
    assert failed_summary.mrr == pytest.approx(1.0)
    assert ret.reciprocal_rank == pytest.approx(1.0)
    assert failed_summary.lexical_concept_coverage is None
    assert failed_summary.citation_presence_rate is None
    assert failed_summary.explicit_citation_rate is None
    assert failed_summary.citation_grounding_validity_rate is None
    assert failed_summary.false_refusal_rate is None
    assert failed_summary.refusal_accuracy is None
    assert failed_summary.clarification_accuracy is None

    # Empty dataset & empty retrieval safely yield None on ratio denominators without ZeroDivisionError
    empty_summary = aggregate_rag_eval_metrics([], [], [])
    assert empty_summary.total_cases == 0
    assert empty_summary.error_count == 0
    assert empty_summary.error_rate is None
    assert empty_summary.context_noise_rate is None
    assert empty_summary.explicit_citation_rate is None
    assert empty_summary.citation_grounding_validity_rate is None

    empty_ret = evaluate_retrieval_case(ans_case, [])
    assert empty_ret.context_noise_rate is None
    assert aggregate_rag_eval_metrics([ans_case], [empty_ret], [ans]).context_noise_rate is None


def test_explicit_vs_fallback_citation_classification():
    c1 = RAGEvalCase(
        id="c_explicit",
        category="answerable_direct",
        question="Q1",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
    )
    c2 = RAGEvalCase(
        id="c_fallback",
        category="answerable_direct",
        question="Q2",
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p2_c1"],
    )
    chunks1 = [{"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "Merge sort O(n log n).", "similarity": 0.80}]
    chunks2 = [{"chunk_id": "dsa_algorithms_pdf_p2_c1", "document_name": "dsa_algorithms.pdf", "page_number": 2, "text": "Binary search O(log n).", "similarity": 0.78}]

    a_explicit = evaluate_answer_case(
        c1,
        QueryResponse(
            answer="Merge sort runs in O(n log n) [Document: dsa_algorithms.pdf, Page: 1].",
            citations=[Citation(document_name="dsa_algorithms.pdf", page_number=1, snippet="Merge sort O(n log n).")],
            insufficient_context=False,
            retrieved_chunks_count=1,
        ),
        chunks1,
    )
    a_fallback = evaluate_answer_case(
        c2,
        QueryResponse(
            answer="Binary search runs in O(log n) time.",
            citations=[Citation(document_name="dsa_algorithms.pdf", page_number=2, snippet="Binary search O(log n).")],
            insufficient_context=False,
            retrieved_chunks_count=1,
        ),
        chunks2,
    )

    assert a_explicit.citation_present is True
    assert a_explicit.explicit_citation is True
    assert a_fallback.citation_present is True
    assert a_fallback.explicit_citation is False

    summary = aggregate_rag_eval_metrics(
        [c1, c2],
        [evaluate_retrieval_case(c1, chunks1), evaluate_retrieval_case(c2, chunks2)],
        [a_explicit, a_fallback],
    )
    assert summary.citation_presence_rate == pytest.approx(1.0)
    assert summary.explicit_citation_rate == pytest.approx(0.5)


def test_context_noise_rate_uses_actual_retrieved_similarities():
    c1 = RAGEvalCase(
        id="noise_1",
        category="answerable_direct",
        question="Q1",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["c1"],
    )
    c2 = RAGEvalCase(
        id="noise_2",
        category="answerable_direct",
        question="Q2",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["c5"],
    )
    u1 = RAGEvalCase(
        id="unans_ignored",
        category="unanswerable",
        question="Q3",
        top_k=4,
        answerable=False,
    )

    ret1 = evaluate_retrieval_case(
        c1,
        [
            {"chunk_id": "c1", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "a", "similarity": 0.72},
            {"chunk_id": "c2", "document_name": "dsa_algorithms.pdf", "page_number": 2, "text": "b", "similarity": 0.28},
            {"chunk_id": "c3", "document_name": "db.pdf", "page_number": 1, "text": "c", "similarity": 0.21},
            {"chunk_id": "c4", "document_name": "os.pdf", "page_number": 1, "text": "d", "similarity": 0.15},
        ],
        similarity_threshold=0.35,
    )
    ret2 = evaluate_retrieval_case(
        c2,
        [
            {"chunk_id": "c5", "document_name": "dsa_algorithms.pdf", "page_number": 3, "text": "e", "similarity": 0.65},
            {"chunk_id": "c6", "document_name": "db.pdf", "page_number": 2, "text": "f", "similarity": 0.40},
        ],
        similarity_threshold=0.35,
    )
    ret_u = evaluate_retrieval_case(
        u1,
        [{"chunk_id": "c7", "document_name": "os.pdf", "page_number": 2, "text": "g", "similarity": 0.11}],
        similarity_threshold=0.35,
    )

    assert ret1.context_noise_rate == pytest.approx(0.75)
    assert ret2.context_noise_rate == pytest.approx(0.0)
    assert ret_u.context_noise_rate is None

    dummy_ans_1 = evaluate_answer_case(c1, QueryResponse(answer="Ok", citations=[], retrieved_chunks_count=4), [])
    dummy_ans_2 = evaluate_answer_case(c2, QueryResponse(answer="Ok", citations=[], retrieved_chunks_count=2), [])
    dummy_ans_u = evaluate_answer_case(u1, QueryResponse(answer="Refused", citations=[], insufficient_context=True), [])

    summary = aggregate_rag_eval_metrics([c1, c2, u1], [ret1, ret2, ret_u], [dummy_ans_1, dummy_ans_2, dummy_ans_u])
    # 3 below-threshold chunks across 6 scored answerable chunks = 0.5 (unanswerable excluded)
    assert summary.context_noise_rate == pytest.approx(0.5)


def test_raw_retrieval_metrics_unchanged_while_filtered_context_reduces_noise_and_scopes_grounding():
    case = RAGEvalCase(
        id="raw_vs_ctx",
        category="answerable_direct",
        question="What is merge sort complexity?",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
        expected_chunk_ids=["dsa_algorithms_pdf_p1_c0"],
        expected_answer_concepts=["O(n log n)"],
    )
    raw_chunks = [
        {"chunk_id": "dsa_algorithms_pdf_p1_c0", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "Merge sort O(n log n).", "similarity": 0.75},
        {"chunk_id": "noise_1", "document_name": "db.pdf", "page_number": 2, "text": "B-Tree.", "similarity": 0.28},
        {"chunk_id": "noise_2", "document_name": "os.pdf", "page_number": 1, "text": "TLB.", "similarity": 0.20},
        {"chunk_id": "noise_3", "document_name": "net.pdf", "page_number": 1, "text": "SYN.", "similarity": 0.15},
    ]
    filtered_context = [raw_chunks[0]]

    # 1. Raw retrieval metrics stay identical over 4 raw chunks while context_noise_rate evaluates filtered context
    ret_m = evaluate_retrieval_case(case, raw_chunks, context_chunks=filtered_context, similarity_threshold=0.35)
    assert ret_m.precision_at_k == pytest.approx(0.25)
    assert ret_m.recall_at_k == pytest.approx(1.0)
    assert ret_m.reciprocal_rank == pytest.approx(1.0)
    assert ret_m.context_noise_rate == pytest.approx(0.0)

    # 2. Trace constructed WITHOUT context_chunks remains backward compatible
    legacy_trace = RAGTrace(standalone_query="What is merge sort complexity?", retrieved_chunks=raw_chunks, max_similarity=0.75)
    assert legacy_trace.context_chunks is None

    # 3. With trace.context_chunks set, citing a filtered-out raw chunk must fail citation grounding
    traced_filtered = RAGTrace(
        standalone_query="What is merge sort complexity?",
        retrieved_chunks=raw_chunks,
        context_chunks=filtered_context,
        max_similarity=0.75,
    )
    citing_filtered_out = QueryResponse(
        answer="Merge sort takes O(n log n) [Document: db.pdf, Page: 2].",
        citations=[],
        insufficient_context=False,
        retrieved_chunks_count=1,
    )
    ans_bad_cite = evaluate_answer_case(case, citing_filtered_out, raw_chunks, trace=traced_filtered)
    assert ans_bad_cite.hallucinated_citation_tags == 1
    assert ans_bad_cite.citations_grounded is False


def test_context_reduction_diagnostics_normal_and_edge_cases():
    a1 = RAGEvalCase(
        id="ans_1",
        category="answerable_direct",
        question="Q1",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
    )
    a2 = RAGEvalCase(
        id="ans_2",
        category="conversational_followup",
        question="Q2",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
    )
    a_empty = RAGEvalCase(
        id="ans_empty",
        category="answerable_direct",
        question="Q3",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
    )
    u_gated = RAGEvalCase(
        id="unans_gated",
        category="unanswerable",
        question="Q4",
        top_k=4,
        answerable=False,
    )
    amb_clar = RAGEvalCase(
        id="amb_clar",
        category="ambiguous",
        question="Explain that",
        top_k=4,
        answerable=False,
        expect_clarification=True,
    )

    raw_4 = [
        {"chunk_id": "c1", "document_name": "dsa_algorithms.pdf", "page_number": 1, "text": "t1", "similarity": 0.72},
        {"chunk_id": "c2", "document_name": "dsa_algorithms.pdf", "page_number": 2, "text": "t2", "similarity": 0.55},
        {"chunk_id": "c3", "document_name": "db.pdf", "page_number": 1, "text": "t3", "similarity": 0.25},
        {"chunk_id": "c4", "document_name": "os.pdf", "page_number": 1, "text": "t4", "similarity": 0.12},
    ]

    ret_a1 = evaluate_retrieval_case(a1, raw_4, context_chunks=raw_4[:1], similarity_threshold=0.35)
    ret_a2 = evaluate_retrieval_case(a2, raw_4, context_chunks=raw_4[:2], similarity_threshold=0.35)
    ret_empty = evaluate_retrieval_case(a_empty, [], context_chunks=[], similarity_threshold=0.35)
    ret_u = evaluate_retrieval_case(u_gated, raw_4, context_chunks=[], similarity_threshold=0.35)
    ret_amb = evaluate_retrieval_case(amb_clar, [], context_chunks=[], similarity_threshold=0.35)

    assert ret_a1.filtered_chunks_count == 3
    assert ret_a1.context_retention_ratio == pytest.approx(0.25)
    assert ret_a2.filtered_chunks_count == 2
    assert ret_a2.context_retention_ratio == pytest.approx(0.5)
    assert ret_empty.filtered_chunks_count == 0
    assert ret_empty.context_retention_ratio is None
    assert ret_u.filtered_chunks_count == 4
    assert ret_u.context_retention_ratio == pytest.approx(0.0)
    assert ret_amb.filtered_chunks_count == 0
    assert ret_amb.context_retention_ratio is None

    # Safety clamp: filtered_chunks_count must never be negative even on synthetic mismatched counts
    ret_clamped = evaluate_retrieval_case(a1, raw_4[:1], context_chunks=raw_4[:2], similarity_threshold=0.35)
    assert ret_clamped.filtered_chunks_count == 0

    ans_ok = QueryResponse(answer="Ans [Document: dsa_algorithms.pdf, Page: 1].", citations=[], retrieved_chunks_count=1)
    ans_err = QueryResponse(answer="Error", citations=[], insufficient_context=False, is_error=True, retrieved_chunks_count=2)
    ans_empty = QueryResponse(answer="Refused", citations=[], insufficient_context=True, retrieved_chunks_count=0)
    ans_ref = QueryResponse(answer="Not enough context.", citations=[], insufficient_context=True, retrieved_chunks_count=0)
    ans_clar = QueryResponse(answer="Could you clarify?", citations=[], clarification_needed=True, retrieved_chunks_count=0)

    summary = aggregate_rag_eval_metrics(
        [a1, a2, a_empty, u_gated, amb_clar],
        [ret_a1, ret_a2, ret_empty, ret_u, ret_amb],
        [
            evaluate_answer_case(a1, ans_ok, raw_4),
            evaluate_answer_case(a2, ans_err, raw_4),
            evaluate_answer_case(a_empty, ans_empty, []),
            evaluate_answer_case(u_gated, ans_ref, raw_4),
            evaluate_answer_case(amb_clar, ans_clar, []),
        ],
    )
    # Answerable with raw > 0: (1 + 2) / (4 + 4) = 0.375; empty answerable excluded from denominator
    assert summary.context_retention_ratio == pytest.approx(0.375)
    # Across all 3 answerable non-clarification cases (a1=1, a2=2, a_empty=0): mean = 1.0
    assert summary.mean_context_chunks_per_answerable_query == pytest.approx(1.0)


def test_context_reduction_diagnostics_zero_raw_and_no_answerable_cases():
    a_empty = RAGEvalCase(
        id="ans_empty_only",
        category="answerable_direct",
        question="Question?",
        top_k=4,
        answerable=True,
        expected_documents=["dsa_algorithms.pdf"],
    )
    ret_empty = evaluate_retrieval_case(a_empty, [], context_chunks=[], similarity_threshold=0.35)
    ans_empty = evaluate_answer_case(
        a_empty,
        QueryResponse(answer="No context", citations=[], insufficient_context=True, retrieved_chunks_count=0),
        [],
    )
    zero_raw_summary = aggregate_rag_eval_metrics([a_empty], [ret_empty], [ans_empty])
    assert zero_raw_summary.context_retention_ratio is None
    assert zero_raw_summary.mean_context_chunks_per_answerable_query == pytest.approx(0.0)

    u_only = RAGEvalCase(
        id="unans_only",
        category="unanswerable",
        question="Unanswerable question?",
        top_k=4,
        answerable=False,
    )
    clar_only = RAGEvalCase(
        id="clar_only",
        category="ambiguous",
        question="Explain that",
        top_k=4,
        answerable=False,
        expect_clarification=True,
    )
    raw_unans = [{"chunk_id": "u1", "document_name": "os.pdf", "page_number": 1, "text": "x", "similarity": 0.1}]
    ret_u = evaluate_retrieval_case(u_only, raw_unans, context_chunks=[], similarity_threshold=0.35)
    ret_c = evaluate_retrieval_case(clar_only, [], context_chunks=[], similarity_threshold=0.35)
    ans_u = evaluate_answer_case(u_only, QueryResponse(answer="Refused", citations=[], insufficient_context=True), raw_unans)
    ans_c = evaluate_answer_case(clar_only, QueryResponse(answer="Clarify?", citations=[], clarification_needed=True), [])

    no_ans_summary = aggregate_rag_eval_metrics([u_only, clar_only], [ret_u, ret_c], [ans_u, ans_c])
    assert no_ans_summary.context_retention_ratio is None
    assert no_ans_summary.mean_context_chunks_per_answerable_query is None

