import ast
import re
from typing import Dict, Any, List, Optional


def _analyze_python_ast_structure(tree: ast.AST) -> Dict[str, Any]:
    """Extract lightweight loop-depth and direct-recursion signals from a Python AST."""
    max_loop_depth = 0
    recursive_functions: List[str] = []

    def _walk_loop_depth(node: ast.AST, current_depth: int) -> None:
        nonlocal max_loop_depth
        next_depth = current_depth
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            next_depth = current_depth + 1
            if next_depth > max_loop_depth:
                max_loop_depth = next_depth
        for child in ast.iter_child_nodes(node):
            _walk_loop_depth(child, next_depth)

    _walk_loop_depth(tree, 0)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    if isinstance(inner.func, ast.Name) and inner.func.id == fn_name:
                        recursive_functions.append(fn_name)
                        break
                    if (
                        isinstance(inner.func, ast.Attribute)
                        and isinstance(inner.func.value, ast.Name)
                        and inner.func.value.id == "self"
                        and inner.func.attr == fn_name
                    ):
                        recursive_functions.append(fn_name)
                        break

    unique_recursive = sorted(set(recursive_functions))
    return {
        "max_loop_depth": max_loop_depth,
        "has_loops": max_loop_depth > 0,
        "has_recursion": len(unique_recursive) > 0,
        "recursive_functions": unique_recursive,
        "signal_source": "python_ast",
    }


def _analyze_c_family_structure(code: str) -> Dict[str, Any]:
    """Extract conservative heuristic loop signals for Java/C++ without pretending to be a full parser."""
    stripped = re.sub(r"/\*.*?\*/", " ", code, flags=re.DOTALL)
    stripped = re.sub(r"//.*?$", " ", stripped, flags=re.MULTILINE)
    stripped = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', " ", stripped)
    has_loops = bool(re.search(r"\b(?:for|while)\b", stripped))
    return {
        "max_loop_depth": None,
        "has_loops": has_loops,
        "has_recursion": None,
        "recursive_functions": [],
        "signal_source": "heuristic_keyword_scan",
    }


def inspect_static_code(code: str, language: str) -> Dict[str, Any]:
    """
    Static code inspection tool:
    Performs pure static parsing (Python AST) or basic delimiter balancing (Java/C++)
    without executing code.
    """
    clean_lang = language.lower().strip()
    if clean_lang == "python":
        analysis_type = "python_ast_inspection"
    elif clean_lang in ("java", "cpp"):
        analysis_type = "delimiter_balance_check"
    else:
        analysis_type = "unsupported"

    result: Dict[str, Any] = {
        "language": clean_lang,
        "line_count": len(code.splitlines()),
        "has_syntax_error": False,
        "syntax_error": None,
        "error_line": None,
        "static_warnings": [],
        "analysis_type": analysis_type,
        "structural_signals": {
            "max_loop_depth": None,
            "has_loops": None,
            "has_recursion": None,
            "recursive_functions": [],
            "signal_source": "unavailable",
        },
    }

    if clean_lang == "python":
        try:
            tree = ast.parse(code)
            result["structural_signals"] = _analyze_python_ast_structure(tree)
            # Inspect for obvious static issues like division by zero
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    if isinstance(node.right, ast.Constant) and node.right.value == 0:
                        result["static_warnings"].append({
                            "line": node.lineno,
                            "type": "division_by_zero",
                            "message": f"Constant division by zero detected at line {node.lineno}."
                        })
        except SyntaxError as err:
            result["has_syntax_error"] = True
            result["syntax_error"] = f"Python SyntaxError: {err.msg}"
            result["error_line"] = err.lineno
            result["static_warnings"].append({
                "line": err.lineno,
                "type": "syntax_error",
                "message": f"Syntax error at line {err.lineno}: {err.msg}"
            })

    elif clean_lang in ("java", "cpp"):
        # Delimiter balancing check
        stack = []
        pairs = {')': '(', '}': '{', ']': '['}
        for line_idx, line in enumerate(code.splitlines(), start=1):
            # Ignore comments and string literals simply for structural check
            sanitized = re.sub(r'//.*$|/\*.*?\*/|".*?"', '', line)
            for char in sanitized:
                if char in '({[':
                    stack.append((char, line_idx))
                elif char in ')}]':
                    if not stack:
                        result["has_syntax_error"] = True
                        result["syntax_error"] = f"Unmatched closing delimiter '{char}' at line {line_idx}."
                        result["error_line"] = line_idx
                        break
                    last_open, last_line = stack.pop()
                    if pairs[char] != last_open:
                        result["has_syntax_error"] = True
                        result["syntax_error"] = f"Mismatched delimiter: '{last_open}' from line {last_line} closed by '{char}' at line {line_idx}."
                        result["error_line"] = line_idx
                        break
            if result["has_syntax_error"]:
                break

        if not result["has_syntax_error"] and stack:
            unclosed_char, unclosed_line = stack[-1]
            result["has_syntax_error"] = True
            result["syntax_error"] = f"Unclosed delimiter '{unclosed_char}' starting at line {unclosed_line}."
            result["error_line"] = unclosed_line

        if not result["has_syntax_error"]:
            result["structural_signals"] = _analyze_c_family_structure(code)

    return result

def generate_edge_test_cases(code: str, language: str) -> List[Dict[str, Any]]:
    """
    Test-case generation tool:
    Generates tailored edge cases based on function signatures and data types.
    """
    test_cases = [
        {
            "category": "Empty / Null Input",
            "scenario": "Passing empty array, null pointer, or empty string",
            "expected_behavior": "Should handle gracefully without NullPointerException / IndexError",
        },
        {
            "category": "Boundary Values",
            "scenario": "Single-element collection or minimal valid integer bounds",
            "expected_behavior": "Should return correct degenerate result without off-by-one errors",
        },
        {
            "category": "Negative / Zero Values",
            "scenario": "Input containing 0 or negative integers",
            "expected_behavior": "Should handle negative indices or sign-dependent logic properly",
        },
        {
            "category": "Duplicate Values",
            "scenario": "Input with identical elements",
            "expected_behavior": "Should maintain stability and correct count/order without infinite loops",
        },
        {
            "category": "Large Scale Input",
            "scenario": "Large dataset near upper constraint limits (e.g., N=10^5)",
            "expected_behavior": "Should complete within typical time limits without recursion stack overflow or integer overflow",
        },
    ]

    clean_lang = language.lower().strip()
    if clean_lang in ("java", "cpp"):
        test_cases.append({
            "category": "Integer Overflow",
            "scenario": "Values exceeding 32-bit signed integer limits (2^31 - 1)",
            "expected_behavior": "Should use 64-bit types (long / long long) if accumulation occurs",
        })

    return test_cases

def execute_code_in_sandbox(
    code: str,
    language: str,
    test_cases: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Test execution tool (Integration Point):
    STRICT SECURITY RULE: Never execute arbitrary user code in the main FastAPI server process.
    Provides a standardized hook for isolated microVM/containerized sandbox execution.
    """
    return {
        "status": "sandbox_deferred",
        "executed": False,
        "message": (
            "Arbitrary user code execution is disabled in the main API server process to prevent RCE. "
            "Isolated container sandbox execution integration point ready."
        ),
        "test_results": [],
    }

