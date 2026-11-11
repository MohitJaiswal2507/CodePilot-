"""
CLI Evaluation Runner for CodePilot AI.

Examples:
    python -m evals.runner --suite rag --mode offline
    python -m evals.runner --suite rag --mode live
    python -m evals.runner --suite rag --mode live --judge
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from evals.rag_evaluator import DEFAULT_RAG_RESULTS_DIR, run_rag_evaluation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.runner",
        description="Run isolated CodePilot AI evaluation suites.",
    )
    parser.add_argument(
        "--suite",
        choices=["rag"],
        default="rag",
        help="Evaluation suite to run (currently: rag).",
    )
    parser.add_argument(
        "--mode",
        choices=["offline", "live"],
        default="offline",
        help="Execution mode: 'offline' (deterministic, zero Gemini calls) or 'live' (calls Gemini gateway).",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Enable optional Gemini-as-a-judge scoring (only valid with --mode live).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Override top-k retrieval count across all cases (1-20).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_RAG_RESULTS_DIR,
        help=f"Directory for JSON and CSV reports (default: {DEFAULT_RAG_RESULTS_DIR}).",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Optional path to a custom RAG evaluation dataset JSON file.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Optional Gemini model override when running in --mode live.",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help="Optional Gemini model override for --judge evaluation.",
    )
    parser.add_argument(
        "--case-ids",
        type=str,
        default=None,
        help="Optional comma-separated case IDs to evaluate (e.g., rag_ans_01,rag_conv_01,rag_unans_01).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional positive integer limiting evaluation to the first N cases in dataset order.",
    )
    parser.add_argument(
        "--save-answers",
        action="store_true",
        help="Opt-in: include standalone_query and generated_answer in the local JSON report (omitted by default).",
    )
    return parser


def _parse_case_ids(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(not p for p in parts):
        raise ValueError("--case-ids must be a non-empty comma-separated list of valid case IDs.")
    if len(parts) != len(set(parts)):
        raise ValueError("--case-ids cannot contain duplicate case IDs.")
    return parts


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Optional[List[str]]:
    if args.judge and args.mode != "live":
        parser.error("--judge requires --mode live and cannot be used in offline mode.")
    if args.top_k is not None and (args.top_k < 1 or args.top_k > 20):
        parser.error("--top-k must be between 1 and 20.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer >= 1.")
    if args.model is not None and args.mode != "live":
        parser.error("--model override is only applicable with --mode live.")
    if args.dataset is not None and not args.dataset.exists():
        parser.error(f"Dataset file not found: {args.dataset}")
    try:
        return _parse_case_ids(args.case_ids)
    except ValueError as exc:
        parser.error(str(exc))


def _fmt_metric(val: Optional[float]) -> str:
    return f"{val:.4f}" if val is not None else "N/A"


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    parsed_case_ids = validate_args(args, parser)

    try:
        report = run_rag_evaluation(
            mode=args.mode,
            dataset_path=args.dataset,
            output_dir=args.output_dir,
            top_k=args.top_k,
            use_judge=args.judge,
            model=args.model,
            judge_model=args.judge_model,
            case_ids=parsed_case_ids,
            limit=args.limit,
            save_answers=args.save_answers,
        )
    except Exception as exc:
        print(f"[ERROR] Evaluation failed: {exc}", file=sys.stderr)
        return 1

    s = report["summary"]
    print(f"=== CodePilot RAG Evaluation ({report['mode'].upper()}) ===")
    print(f"Dataset Version:                  {report['dataset_version']}")
    print(f"Total Cases:                      {s['total_cases']} "
          f"(ans={s['answerable_count']}, unans={s['unanswerable_count']}, amb={s['ambiguous_count']}, err={s.get('error_count', 0)})")
    print(f"Error Rate:                       {_fmt_metric(s.get('error_rate'))}")
    print(f"Precision@K:                      {_fmt_metric(s['precision_at_k'])}")
    print(f"Recall@K:                         {_fmt_metric(s['recall_at_k'])}")
    print(f"MRR:                              {_fmt_metric(s['mrr'])}")
    print(f"Answerable Mean Top-1 Sim:        {_fmt_metric(s['answerable_mean_top1_similarity'])}")
    print(f"Unanswerable Mean Top-1 Sim:      {_fmt_metric(s['unanswerable_mean_top1_similarity'])}")
    print(f"Context Noise Rate:               {_fmt_metric(s.get('context_noise_rate'))}")
    print(f"Context Retention Ratio:          {_fmt_metric(s.get('context_retention_ratio'))}")
    print(f"Mean Context Chunks / Query:      {_fmt_metric(s.get('mean_context_chunks_per_answerable_query'))}")
    print(f"Refusal Accuracy:                 {_fmt_metric(s['refusal_accuracy'])}")
    print(f"False Refusal Rate:               {_fmt_metric(s['false_refusal_rate'])}")
    print(f"Clarification Accuracy:           {_fmt_metric(s['clarification_accuracy'])}")
    print(f"Citation Presence Rate:           {_fmt_metric(s['citation_presence_rate'])}")
    print(f"Explicit Citation Rate:           {_fmt_metric(s.get('explicit_citation_rate'))}")
    print(f"Citation Grounding Validity:      {_fmt_metric(s['citation_grounding_validity_rate'])}")
    print(f"Lexical Concept Coverage:         {_fmt_metric(s['lexical_concept_coverage'])}")

    if report.get("telemetry_summary"):
        tel = report["telemetry_summary"]
        print(f"Gateway Calls / Tokens / Latency: {tel['calls_recorded']} calls, "
              f"total_tokens={tel['total_tokens']}, mean_latency_ms={tel['mean_latency_ms']}")

    if report.get("judge_summary"):
        js = report["judge_summary"]
        print(f"Judge (n={js['evaluated_cases']}):                  "
              f"faithfulness={_fmt_metric(js['mean_faithfulness'])}, "
              f"relevance={_fmt_metric(js['mean_relevance'])}")

    artifacts = report.get("artifacts", {})
    if artifacts:
        print(f"JSON Report:                      {artifacts['json_report']}")
        print(f"CSV Summary:                      {artifacts['csv_summary']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

