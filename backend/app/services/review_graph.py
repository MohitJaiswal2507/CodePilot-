import json
import logging
from typing import Dict, Any, List, Optional, TypedDict
from pydantic import ValidationError
from langgraph.graph import StateGraph, END
from google import genai
from google.genai import types

from app.core.config import settings
from app.services import model_service
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


def ai_review_node(state: ReviewState) -> Dict[str, Any]:
    """Node 3: Execute AI code analysis via Gemini or mock callable."""
    code = state["code"]
    language = state["language"]
    model_name = state.get("model") or settings.GEMINI_MODEL or "gemini-2.5-flash"
    llm_callable = state.get("llm_callable")
    static_inspection = state.get("static_inspection", {})

    static_context = ""
    if static_inspection and static_inspection.get("has_syntax_error"):
        static_context = f"\nSTATIC INSPECTION FINDING: {static_inspection.get('syntax_error')} at line {static_inspection.get('error_line')}."

    prompt = f"""Language: {language}
{static_context}

SOURCE CODE TO REVIEW:
```{language}
{code}
```

Perform the comprehensive review and output strictly the required JSON object.
"""

    if llm_callable:
        response_text = llm_callable(prompt)
    else:
        # Call Gemini SDK
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured.")

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        config = types.GenerateContentConfig(
            system_instruction=REVIEW_SYSTEM_PROMPT,
            temperature=0.2,
            response_mime_type="application/json",
        )
        api_model = model_name
        if api_model.startswith("models/"):
            api_model = api_model[len("models/"):]

        response = client.models.generate_content(
            model=api_model,
            contents=prompt,
            config=config,
        )
        response_text = response.text or "{}"

    # Parse JSON from AI response
    try:
        cleaned_json = response_text.strip()
        if cleaned_json.startswith("```json"):
            cleaned_json = cleaned_json[7:]
        if cleaned_json.startswith("```"):
            cleaned_json = cleaned_json[3:]
        if cleaned_json.endswith("```"):
            cleaned_json = cleaned_json[:-3]
        raw_analysis = json.loads(cleaned_json.strip())
    except Exception as exc:
        logger.warning("Failed to parse raw JSON from AI review: %s. Raw text: %s", exc, response_text[:200])
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
                    "suggestion": "Review submitted code manually."
                }
            ],
            "edge_cases": [],
            "complexity": {
                "time_complexity": "O(n)",
                "time_reasoning": "Default estimate; detailed reasoning unavailable.",
                "space_complexity": "O(1)",
                "space_reasoning": "Default estimate; detailed reasoning unavailable."
            },
            "improvement_suggestions": ["Ensure code compiles cleanly."],
            "corrected_code": code,
            "explanation_of_changes": "No changes generated due to formatting issue."
        }

    return {"raw_ai_analysis": raw_analysis}


def edge_case_analysis_node(state: ReviewState) -> Dict[str, Any]:
    """Node 4: Edge-case boundary synthesis."""
    code = state["code"]
    language = state["language"]
    raw_analysis = state.get("raw_ai_analysis", {})

    model_edge_cases = raw_analysis.get("edge_cases", [])
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

    return {"edge_cases": raw_analysis.get("edge_cases", [])}


def complexity_analysis_node(state: ReviewState) -> Dict[str, Any]:
    """Node 5: Complexity verification and refinement."""
    raw_analysis = state.get("raw_ai_analysis", {})
    comp = raw_analysis.get("complexity", {})

    if not comp or not comp.get("time_complexity"):
        comp = {
            "time_complexity": "O(n)",
            "time_reasoning": "Standard traversal of input collection.",
            "space_complexity": "O(1)",
            "space_reasoning": "Uses fixed auxiliary variables without additional data structures.",
        }
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

    raw = state.get("raw_ai_analysis", {})
    static_inspection = state.get("static_inspection", {})

    # Add static syntax errors to detected issues if not already reported
    detected = raw.get("detected_issues", [])
    if static_inspection and static_inspection.get("has_syntax_error"):
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
    if assessment not in valid_assessments:
        assessment = "needs_improvement"

    score = raw.get("quality_score", 5)
    try:
        score = max(1, min(10, int(score)))
    except (ValueError, TypeError):
        score = 5

    comp_dict = raw.get("complexity", {})
    complexity = ComplexityAnalysis(
        time_complexity=comp_dict.get("time_complexity", "O(n)"),
        time_reasoning=comp_dict.get("time_reasoning", "Analysis of primary computational loops."),
        space_complexity=comp_dict.get("space_complexity", "O(1)"),
        space_reasoning=comp_dict.get("space_reasoning", "Evaluation of auxiliary memory allocations."),
    )

    issues = []
    for item in detected:
        try:
            issues.append(CodeReviewIssue(
                type=item.get("type", "warning"),
                severity=item.get("severity", "medium"),
                message=item.get("message", "Potential issue identified."),
                line_number=item.get("line_number"),
                suggestion=item.get("suggestion"),
            ))
        except ValidationError:
            continue

    edge_cases = []
    for ec in raw.get("edge_cases", []):
        try:
            edge_cases.append(EdgeCaseAnalysis(
                category=ec.get("category", "Boundary Condition"),
                scenario=ec.get("scenario", "Input scenario"),
                behavior=ec.get("behavior", "Observed behavior"),
                handled=bool(ec.get("handled", False)),
            ))
        except ValidationError:
            continue

    static_notes = "Static syntax verification passed." if not static_inspection.get("has_syntax_error") else f"Static analysis detected syntax error: {static_inspection.get('syntax_error')}"

    result = CodeReviewResult(
        summary=raw.get("summary", "Code review completed successfully."),
        overall_assessment=assessment,
        quality_score=score,
        detected_issues=issues,
        edge_cases=edge_cases,
        complexity=complexity,
        improvement_suggestions=raw.get("improvement_suggestions", []),
        corrected_code=raw.get("corrected_code"),
        explanation_of_changes=raw.get("explanation_of_changes"),
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

