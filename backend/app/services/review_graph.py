import json
import logging
import re
from typing import Dict, Any, List, Optional, TypedDict
from pydantic import ValidationError
from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.services import model_service
from app.services.llm_gateway import LLMGenerationResult, generate_text
from app.services.observability import LLMTelemetryEvent, record_llm_telemetry
from app.schemas.reviewer import (
    CodeReviewResult,
    CodeReviewIssue,
    EdgeCaseAnalysis,
    ComplexityAnalysis,
)
from app.services.reviewer_tools import (
    inspect_static_code,
    generate_edge_test_cases,
    execute_code_in_sandbox,
)

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = """You are CodePilot AI, a Principal Software Engineer and Staff Code Reviewer.
Your role is to perform rigorous, constructive, and comprehensive code reviews on student and developer submissions.

LANGUAGES SUPPORTED: Python, Java, C++.

CRITICAL REVIEW GUIDELINES:
1. BUG DETECTION: Identify logical errors, off-by-one errors, incorrect conditions, wrong variable usage, and potential runtime crashes.
2. LINE NUMBERS: Give precise, reliable line numbers for detected bugs based on the submitted code. Do NOT invent line numbers.
3. EDGE CASES: Systematically analyze empty inputs, boundary values, negative numbers, duplicates, and large inputs.
4. COMPLEXITY: State exact Big-O Time Complexity and Big-O Auxiliary Space Complexity, explaining the step-by-step reasoning.
5. CODE QUALITY: Assess naming, readability, modularity, and unnecessary operations.
6. CORRECTED CODE: Provide a complete, idiomatic, and corrected version preserving original algorithmic intent.
7. STATIC ANALYSIS DISTINCTION: Clearly state that your findings are derived from static semantic analysis and not physical execution.

OUTPUT FORMAT:
You MUST respond with valid JSON matching this exact structure:
{
  "summary": "High-level summary of the code and primary findings.",
  "overall_assessment": "excellent" | "good" | "needs_improvement" | "problematic" | "critical_bugs",
  "quality_score": 1 to 10 (integer),
  "detected_issues": [
    {
      "type": "bug" | "error" | "warning" | "performance" | "style" | "security",
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "message": "Clear explanation of the problem.",
      "line_number": 1-based integer or null,
      "suggestion": "How to resolve this issue."
    }
  ],
  "edge_cases": [
    {
      "category": "Empty Input" | "Boundary Values" | "Negative Values" | "Duplicate Values" | "Large Scale",
      "scenario": "Description of the edge scenario",
      "behavior": "How the code responds",
      "handled": true | false
    }
  ],
  "complexity": {
    "time_complexity": "O(...)",
    "time_reasoning": "Detailed explanation of time complexity.",
    "space_complexity": "O(...)",
    "space_reasoning": "Detailed explanation of space complexity."
  },
  "improvement_suggestions": [
    "Suggestion 1",
    "Suggestion 2"
  ],
  "corrected_code": "Full corrected source code here",
  "explanation_of_changes": "Detailed explanation of why each correction was made."
}
"""

class ReviewState(TypedDict, total=False):
    code: str
    language: str
    model: str
    user_id: str
    is_valid: bool
    validation_error: Optional[str]
    static_inspection: Optional[Dict[str, Any]]
    raw_ai_analysis: Optional[Dict[str, Any]]
    edge_cases: Optional[List[Dict[str, Any]]]
    complexity: Optional[Dict[str, Any]]
    final_result: Optional[CodeReviewResult]
    llm_callable: Optional[Any]


# -----------------------------------------------------------------------------
# LangGraph Workflow Nodes
# -----------------------------------------------------------------------------

def validate_input_node(state: ReviewState) -> Dict[str, Any]:
    """Node 1: Validate input code and language."""
    code = (state.get("code") or "").strip()
    language = (state.get("language") or "").lower().strip()

    if not code:
        return {
            "is_valid": False,
            "validation_error": "Submitted code cannot be empty.",
        }

    if len(code) < 2:
        return {
            "is_valid": False,
            "validation_error": "Submitted code is too short for meaningful analysis.",
        }

    if len(code) > 50000:
        return {
            "is_valid": False,
            "validation_error": "Submitted code exceeds maximum limit of 50,000 characters.",
        }

    supported_languages = {"python", "java", "cpp"}
    if language not in supported_languages:
        return {
            "is_valid": False,
            "validation_error": f"Unsupported language '{language}'. Supported languages: Python, Java, C++.",
        }

    return {"is_valid": True, "validation_error": None}


def should_continue_review(state: ReviewState) -> str:
    """Conditional Edge: check if validation succeeded."""
    return "continue" if state.get("is_valid", False) else "invalid"


def static_analysis_node(state: ReviewState) -> Dict[str, Any]:
    """Node 2: Static syntax and delimiter inspection."""
    code = state["code"]
    language = state["language"]
    inspection = inspect_static_code(code, language)
    return {"static_inspection": inspection}


# -----------------------------------------------------------------------------
# Defensive JSON Extraction & Field Normalization Helpers
# -----------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_LEADING_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_TRAILING_FENCE_RE = re.compile(r"\s*```\s*$")

_COMPLEXITY_UNAVAILABLE_MSG = "Complexity could not be verified from model output."
_UNAVAILABLE_COMPLEXITY: Dict[str, str] = {
    "time_complexity": "N/A",
    "time_reasoning": _COMPLEXITY_UNAVAILABLE_MSG,
    "space_complexity": "N/A",
    "space_reasoning": _COMPLEXITY_UNAVAILABLE_MSG,
}


def _extract_json_dict(raw_text: Any) -> Dict[str, Any]:
    """
    Parse model output into a top-level JSON dictionary.
    Supports raw JSON and markdown-fenced JSON (case-insensitive, with surrounding prose).
    Raises ValueError on empty, malformed, or non-dict JSON outputs.
    """
    if not isinstance(raw_text, str):
        raise ValueError(f"Expected string response, got {type(raw_text).__name__}.")

    stripped = raw_text.strip()
    if not stripped:
        raise ValueError("Model returned an empty or whitespace-only response.")

    candidates: List[str] = [stripped]
    if stripped.startswith("```"):
        unfenced = _TRAILING_FENCE_RE.sub("", _LEADING_FENCE_RE.sub("", stripped, count=1), count=1).strip()
        if unfenced:
            candidates.append(unfenced)

    for match in _JSON_FENCE_RE.finditer(raw_text):
        block = match.group(1).strip()
        if block:
            candidates.append(block)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Expected top-level JSON object, got {type(parsed).__name__}.")

    raise ValueError("Model output could not be parsed as a JSON object.")


def _normalize_dict_list(value: Any) -> List[Dict[str, Any]]:
    """Return a shallow list containing only dictionary items from a list value."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_complexity_dict(value: Any) -> Dict[str, str]:
    """Normalize complexity analysis dict safely without inventing Big-O claims."""
    if not isinstance(value, dict):
        return dict(_UNAVAILABLE_COMPLEXITY)

    def _clean_str(val: Any) -> Optional[str]:
        if isinstance(val, str) and val.strip():
            return val.strip()
        return None

    time_c = _clean_str(value.get("time_complexity"))
    space_c = _clean_str(value.get("space_complexity"))
    time_r = _clean_str(value.get("time_reasoning"))
    space_r = _clean_str(value.get("space_reasoning"))

    return {
        "time_complexity": time_c or "N/A",
        "time_reasoning": time_r or _COMPLEXITY_UNAVAILABLE_MSG,
        "space_complexity": space_c or "N/A",
        "space_reasoning": space_r or _COMPLEXITY_UNAVAILABLE_MSG,
    }


def _normalize_improvement_suggestions(value: Any) -> List[str]:
    """Accept a list of non-empty strings or coerce a single non-empty string."""
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def ai_review_node(state: ReviewState) -> Dict[str, Any]:
    """Node 3: Execute AI code analysis via Gemini or mock callable."""
    code = state["code"]
    language = state["language"]
    model_name = state.get("model") or settings.GEMINI_MODEL or "gemini-2.5-flash"
    llm_callable = state.get("llm_callable")
    static_inspection = state.get("static_inspection")
    if not isinstance(static_inspection, dict):
        static_inspection = {}

    static_context = ""
    if static_inspection.get("has_syntax_error"):
        static_context = f"\nSTATIC INSPECTION FINDING: {static_inspection.get('syntax_error')} at line {static_inspection.get('error_line')}."

    prompt = f"""Language: {language}
{static_context}

SOURCE CODE TO REVIEW:
```{language}
{code}
```

Perform the comprehensive review and output strictly the required JSON object.
"""

    gw_result: Optional[LLMGenerationResult] = None
    if llm_callable:
        response_text = llm_callable(prompt)
    else:
        gw_result = generate_text(
            prompt=prompt,
            system_instruction=REVIEW_SYSTEM_PROMPT,
            model=model_name,
            temperature=0.2,
            response_mime_type="application/json",
            feature="code_review",
            allow_fallback=False,
        )
        response_text = gw_result.text

    # Parse JSON from AI response (only top-level JSON objects are valid)
    try:
        raw_analysis = _extract_json_dict(response_text)
    except Exception as exc:
        logger.warning("Failed to parse structured JSON from AI review (%s)", type(exc).__name__)
        record_llm_telemetry(
            LLMTelemetryEvent(
                event_type="json_parse_fallback",
                feature="code_review",
                model_used=gw_result.model_used if gw_result else model_name,
                model_version=gw_result.model_version if gw_result else None,
                prompt_tokens=gw_result.prompt_tokens if gw_result else None,
                output_tokens=gw_result.output_tokens if gw_result else None,
                total_tokens=gw_result.total_tokens if gw_result else None,
                thoughts_tokens=gw_result.thoughts_tokens if gw_result else None,
                latency_ms=gw_result.latency_ms if gw_result else 0.0,
                retries=gw_result.retries if gw_result else 0,
                fallback_used=gw_result.fallback_used if gw_result else False,
                success=False,
                error_category="json_parse_error",
                parse_fallback=True,
            )
        )
        raw_analysis = {
            "summary": "Code review completed with unstructured output.",
            "overall_assessment": "needs_improvement",
            "quality_score": 5,
            "detected_issues": [
                {
                    "type": "warning",
                    "severity": "medium",
                    "message": "AI model output could not be parsed into strictly structured JSON.",
                    "line_number": None,
                    "suggestion": "Review submitted code manually.",
                }
            ],
            "edge_cases": [],
            "complexity": dict(_UNAVAILABLE_COMPLEXITY),
            "improvement_suggestions": ["Ensure code compiles cleanly."],
            "corrected_code": None,
            "explanation_of_changes": "No changes generated due to formatting issue.",
        }

    return {"raw_ai_analysis": raw_analysis}


def edge_case_analysis_node(state: ReviewState) -> Dict[str, Any]:
    """Node 4: Edge-case boundary synthesis."""
    code = state["code"]
    language = state["language"]
    raw_analysis = state.get("raw_ai_analysis")
    if not isinstance(raw_analysis, dict):
        raw_analysis = {}

    model_edge_cases = _normalize_dict_list(raw_analysis.get("edge_cases"))
    if not model_edge_cases:
        # Synthesize edge cases using static generator tool
        tool_cases = generate_edge_test_cases(code, language)
        synthesized = [
            {
                "category": tc["category"],
                "scenario": tc["scenario"],
                "behavior": tc["expected_behavior"],
                "handled": False,
            }
            for tc in tool_cases
        ]
        raw_analysis["edge_cases"] = synthesized
    else:
        raw_analysis["edge_cases"] = model_edge_cases

    return {"edge_cases": raw_analysis["edge_cases"]}


def complexity_analysis_node(state: ReviewState) -> Dict[str, Any]:
    """Node 5: Complexity verification and refinement."""
    raw_analysis = state.get("raw_ai_analysis")
    if not isinstance(raw_analysis, dict):
        raw_analysis = {}

    comp = _normalize_complexity_dict(raw_analysis.get("complexity"))
    raw_analysis["complexity"] = comp
    return {"complexity": comp}


def format_result_node(state: ReviewState) -> Dict[str, Any]:
    """Node 6: Assemble and validate final structured result."""
    if not state.get("is_valid", False):
        err = state.get("validation_error", "Validation failed.")
        empty_result = CodeReviewResult(
            summary=f"Validation Error: {err}",
            overall_assessment="problematic",
            quality_score=1,
            detected_issues=[
                CodeReviewIssue(
                    type="error",
                    severity="critical",
                    message=err,
                    line_number=None,
                    suggestion="Please submit valid source code in Python, Java, or C++.",
                )
            ],
            edge_cases=[],
            complexity=ComplexityAnalysis(
                time_complexity="N/A",
                time_reasoning="Code could not be validated for complexity analysis.",
                space_complexity="N/A",
                space_reasoning="Code could not be validated for complexity analysis.",
            ),
            improvement_suggestions=["Submit valid code to receive a full review."],
            corrected_code=None,
            explanation_of_changes=None,
            static_analysis_notes=None,
        )
        return {"final_result": empty_result}

    raw = state.get("raw_ai_analysis")
    if not isinstance(raw, dict):
        raw = {}
    static_inspection = state.get("static_inspection")
    if not isinstance(static_inspection, dict):
        static_inspection = {}

    # Add static syntax errors to detected issues if not already reported
    detected = _normalize_dict_list(raw.get("detected_issues"))
    if static_inspection.get("has_syntax_error"):
        syntax_msg = static_inspection.get("syntax_error")
        syntax_line = static_inspection.get("error_line")
        if not any(i.get("line_number") == syntax_line for i in detected):
            detected.insert(0, {
                "type": "error",
                "severity": "critical",
                "message": syntax_msg,
                "line_number": syntax_line,
                "suggestion": "Correct the syntax error before compiling or executing.",
            })

    # Validate overall assessment against schema literals
    assessment = raw.get("overall_assessment", "needs_improvement")
    valid_assessments = {"excellent", "good", "needs_improvement", "problematic", "critical_bugs"}
    if not isinstance(assessment, str) or assessment not in valid_assessments:
        assessment = "needs_improvement"

    score = raw.get("quality_score", 5)
    if isinstance(score, bool):
        score = 5
    else:
        try:
            score = max(1, min(10, int(score)))
        except (ValueError, TypeError):
            score = 5

    comp_dict = _normalize_complexity_dict(raw.get("complexity"))
    complexity = ComplexityAnalysis(
        time_complexity=comp_dict["time_complexity"],
        time_reasoning=comp_dict["time_reasoning"],
        space_complexity=comp_dict["space_complexity"],
        space_reasoning=comp_dict["space_reasoning"],
    )

    issues: List[CodeReviewIssue] = []
    for item in detected:
        raw_msg = item.get("message")
        if not isinstance(raw_msg, str) or not raw_msg.strip():
            continue
        raw_line = item.get("line_number")
        line_num = raw_line if isinstance(raw_line, int) and not isinstance(raw_line, bool) and raw_line >= 1 else None
        raw_sug = item.get("suggestion")
        suggestion = raw_sug.strip() if isinstance(raw_sug, str) and raw_sug.strip() else None
        issue_type = item.get("type") if isinstance(item.get("type"), str) else "warning"
        issue_sev = item.get("severity") if isinstance(item.get("severity"), str) else "medium"
        try:
            issues.append(CodeReviewIssue(
                type=issue_type,  # type: ignore[arg-type]
                severity=issue_sev,  # type: ignore[arg-type]
                message=raw_msg.strip(),
                line_number=line_num,
                suggestion=suggestion,
            ))
        except ValidationError:
            continue

    edge_cases: List[EdgeCaseAnalysis] = []
    for ec in _normalize_dict_list(raw.get("edge_cases")):
        raw_scenario = ec.get("scenario")
        raw_behavior = ec.get("behavior")
        if not (isinstance(raw_scenario, str) and raw_scenario.strip()) and not (
            isinstance(raw_behavior, str) and raw_behavior.strip()
        ):
            continue
        cat = ec.get("category")
        category = cat.strip() if isinstance(cat, str) and cat.strip() else "Boundary Condition"
        scenario = raw_scenario.strip() if isinstance(raw_scenario, str) and raw_scenario.strip() else "Input scenario"
        behavior = raw_behavior.strip() if isinstance(raw_behavior, str) and raw_behavior.strip() else "Observed behavior"
        try:
            edge_cases.append(EdgeCaseAnalysis(
                category=category,
                scenario=scenario,
                behavior=behavior,
                handled=bool(ec.get("handled", False)),
            ))
        except ValidationError:
            continue

    raw_summary = raw.get("summary")
    summary = (
        raw_summary.strip()
        if isinstance(raw_summary, str) and raw_summary.strip()
        else "Code review completed."
    )
    raw_corrected = raw.get("corrected_code")
    corrected_code = raw_corrected if isinstance(raw_corrected, str) and raw_corrected.strip() else None
    raw_explanation = raw.get("explanation_of_changes")
    explanation_of_changes = (
        raw_explanation.strip()
        if isinstance(raw_explanation, str) and raw_explanation.strip()
        else None
    )
    improvements = _normalize_improvement_suggestions(raw.get("improvement_suggestions"))

    static_notes = (
        "Static syntax verification passed."
        if not static_inspection.get("has_syntax_error")
        else f"Static analysis detected syntax error: {static_inspection.get('syntax_error')}"
    )

    result = CodeReviewResult(
        summary=summary,
        overall_assessment=assessment,  # type: ignore[arg-type]
        quality_score=score,
        detected_issues=issues,
        edge_cases=edge_cases,
        complexity=complexity,
        improvement_suggestions=improvements,
        corrected_code=corrected_code,
        explanation_of_changes=explanation_of_changes,
        static_analysis_notes=static_notes,
    )

    return {"final_result": result}


# -----------------------------------------------------------------------------
# LangGraph Workflow Construction
# -----------------------------------------------------------------------------

def build_review_graph():
    builder = StateGraph(ReviewState)

    builder.add_node("validate_input", validate_input_node)
    builder.add_node("static_analysis", static_analysis_node)
    builder.add_node("ai_review", ai_review_node)
    builder.add_node("edge_case_analysis", edge_case_analysis_node)
    builder.add_node("complexity_analysis", complexity_analysis_node)
    builder.add_node("format_result", format_result_node)

    builder.set_entry_point("validate_input")

    builder.add_conditional_edges(
        "validate_input",
        should_continue_review,
        {
            "continue": "static_analysis",
            "invalid": "format_result",
        }
    )

    builder.add_edge("static_analysis", "ai_review")
    builder.add_edge("ai_review", "edge_case_analysis")
    builder.add_edge("edge_case_analysis", "complexity_analysis")
    builder.add_edge("complexity_analysis", "format_result")
    builder.add_edge("format_result", END)

    return builder.compile()

# Singleton compiled workflow
review_workflow = build_review_graph()


def execute_code_review(
    code: str,
    language: str,
    user_id: str,
    model: Optional[str] = None,
    llm_callable: Optional[Any] = None,
) -> CodeReviewResult:
    """
    Public entry point to execute the LangGraph code review workflow.
    """
    initial_state: ReviewState = {
        "code": code,
        "language": language,
        "user_id": user_id,
        "model": model or settings.GEMINI_MODEL,
        "llm_callable": llm_callable,
    }

    final_state = review_workflow.invoke(initial_state)
    result = final_state.get("final_result")

    if not result:
        raise RuntimeError("Code review workflow terminated without producing a final result.")

    return result

