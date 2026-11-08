from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field

class CodeReviewIssue(BaseModel):
    type: Literal["bug", "error", "warning", "performance", "style", "security"] = Field(
        ..., description="Classification of the detected code issue"
    )
    severity: Literal["critical", "high", "medium", "low", "info"] = Field(
        ..., description="Severity level of the issue"
    )
    message: str = Field(..., description="Detailed description of the issue")
    line_number: Optional[int] = Field(None, description="1-based line number if reliably identified, otherwise None")
    suggestion: Optional[str] = Field(None, description="Actionable recommendation to fix the issue")

class EdgeCaseAnalysis(BaseModel):
    category: str = Field(..., description="E.g., Empty/Null input, Boundary values, Large inputs, Negative values, Duplicate values, Overflow")
    scenario: str = Field(..., description="Specific scenario description")
    behavior: str = Field(..., description="Observed or predicted code behavior in this scenario")
    handled: bool = Field(..., description="Whether the code properly accounts for this edge case")

class ComplexityAnalysis(BaseModel):
    time_complexity: str = Field(..., description="Big-O time complexity (e.g., O(n log n))")
    time_reasoning: str = Field(..., description="Step-by-step reasoning for the time complexity")
    space_complexity: str = Field(..., description="Auxiliary space complexity (e.g., O(1))")
    space_reasoning: str = Field(..., description="Step-by-step reasoning for auxiliary space complexity")

class CodeReviewResult(BaseModel):
    summary: str = Field(..., description="Executive summary of the code review findings")
    overall_assessment: Literal["excellent", "good", "needs_improvement", "problematic", "critical_bugs"] = Field(
        ..., description="Overall quality tier of the submitted code"
    )
    quality_score: int = Field(..., ge=1, le=10, description="Overall code quality score out of 10")
    detected_issues: List[CodeReviewIssue] = Field(default_factory=list, description="List of detected bugs, errors, and warnings")
    edge_cases: List[EdgeCaseAnalysis] = Field(default_factory=list, description="Systematic boundary and edge-case evaluation")
    complexity: ComplexityAnalysis = Field(..., description="Time and auxiliary space complexity analysis with reasoning")
    improvement_suggestions: List[str] = Field(default_factory=list, description="Actionable suggestions for code readability and maintainability")
    corrected_code: Optional[str] = Field(None, description="Corrected and optimized version preserving original algorithm intent")
    explanation_of_changes: Optional[str] = Field(None, description="Clear description of changes made in the corrected code")
    static_analysis_notes: Optional[str] = Field(None, description="Notes from static syntax and delimiter verification")

class ReviewCodeRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=50000, description="Source code to review")
    language: Literal["python", "java", "cpp"] = Field(..., description="Programming language of the code")
    model: Optional[str] = Field(None, description="Optional user-selected Gemini model ID")

class CodeReviewResponse(BaseModel):
    id: str = Field(..., description="Unique review identifier")
    language: str
    submitted_code: str
    review: CodeReviewResult
    model_used: str
    created_at: str

class CodeReviewHistoryItem(BaseModel):
    id: str
    language: str
    code_snippet: str
    summary: str
    overall_assessment: str
    quality_score: int
    model_used: str
    created_at: str

class CodeReviewHistoryResponse(BaseModel):
    reviews: List[CodeReviewHistoryItem]
    total: int

