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


def _scan_c_family(code: str) -> Dict[str, Any]:
    """
    Single-pass character scanner for Java/C++.
    Tracks NORMAL, LINE_COMMENT, BLOCK_COMMENT, STRING, and CHAR states,
    preserves newlines, checks (), {}, [] balance, and returns stripped code.
    """
    NORMAL = 0
    LINE_COMMENT = 1
    BLOCK_COMMENT = 2
    STRING = 3
    CHAR = 4

    state = NORMAL
    stripped_chars: List[str] = []
    stack: List[tuple] = []
    pairs = {")": "(", "}": "{", "]": "["}
    has_syntax_error = False
    syntax_error: Optional[str] = None
    error_line: Optional[int] = None

    n = len(code)
    i = 0
    line_idx = 1

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if state == NORMAL:
            if ch == "/" and nxt == "/":
                state = LINE_COMMENT
                stripped_chars.extend([" ", " "])
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = BLOCK_COMMENT
                stripped_chars.extend([" ", " "])
                i += 2
                continue
            if ch == '"':
                state = STRING
                stripped_chars.append(" ")
                i += 1
                continue
            if ch == "'":
                state = CHAR
                stripped_chars.append(" ")
                i += 1
                continue

            stripped_chars.append(ch)
            if not has_syntax_error:
                if ch in "({[":
                    stack.append((ch, line_idx))
                elif ch in ")}]":
                    if not stack:
                        has_syntax_error = True
                        syntax_error = f"Unmatched closing delimiter '{ch}' at line {line_idx}."
                        error_line = line_idx
                    else:
                        last_open, last_line = stack.pop()
                        if pairs[ch] != last_open:
                            has_syntax_error = True
                            syntax_error = (
                                f"Mismatched delimiter: '{last_open}' from line {last_line} "
                                f"closed by '{ch}' at line {line_idx}."
                            )
                            error_line = line_idx

        elif state == LINE_COMMENT:
            if ch == "\n":
                state = NORMAL
                stripped_chars.append("\n")
            else:
                stripped_chars.append(" ")

        elif state == BLOCK_COMMENT:
            if ch == "*" and nxt == "/":
                state = NORMAL
                stripped_chars.extend([" ", " "])
                i += 2
                continue
            stripped_chars.append("\n" if ch == "\n" else " ")

        elif state == STRING:
            if ch == "\\":
                stripped_chars.append(" ")
                if i + 1 < n:
                    if code[i + 1] == "\n":
                        line_idx += 1
                        stripped_chars.append("\n")
                    else:
                        stripped_chars.append(" ")
                    i += 2
                    continue
            elif ch == '"':
                state = NORMAL
                stripped_chars.append(" ")
            elif ch == "\n":
                state = NORMAL
                stripped_chars.append("\n")
            else:
                stripped_chars.append(" ")

        elif state == CHAR:
            if ch == "\\":
                stripped_chars.append(" ")
                if i + 1 < n:
                    if code[i + 1] == "\n":
                        line_idx += 1
                        stripped_chars.append("\n")
                    else:
                        stripped_chars.append(" ")
                    i += 2
                    continue
            elif ch == "'":
                state = NORMAL
                stripped_chars.append(" ")
            elif ch == "\n":
                state = NORMAL
                stripped_chars.append("\n")
            else:
                stripped_chars.append(" ")

        if ch == "\n":
            line_idx += 1
        i += 1

    if not has_syntax_error and stack:
        unclosed_char, unclosed_line = stack[-1]
        has_syntax_error = True
        syntax_error = f"Unclosed delimiter '{unclosed_char}' starting at line {unclosed_line}."
        error_line = unclosed_line

    return {
        "has_syntax_error": has_syntax_error,
        "syntax_error": syntax_error,
        "error_line": error_line,
        "stripped_code": "".join(stripped_chars),
    }


def _collect_c_family_warnings(
    raw_code: str, stripped_code: str, language: str
) -> List[Dict[str, Any]]:
    """Collect conservative, advisory static warnings for Java/C++ without pretending to be a compiler."""
    warnings: List[Dict[str, Any]] = []
    raw_lines = raw_code.splitlines()
    stripped_lines = stripped_code.splitlines()

    def _next_nonempty_stripped(start_idx: int) -> str:
        for j in range(start_idx + 1, len(stripped_lines)):
            cand = stripped_lines[j].strip()
            if cand:
                return cand
        return ""

    control_prefixes = (
        "if", "else", "for", "while", "switch", "try", "catch", "finally",
        "do", "class", "struct", "interface", "enum", "namespace", "template",
        "public:", "private:", "protected:", "case ", "default:",
    )
    continuation_endings = (
        "{", "}", ";", ",", "(", "[", ":", "\\", "+", "-", "*", "/", "%",
        "=", "&", "|", "^", "?", ".", "<", ">", "!", "~", "->",
    )
    continuation_starts = (".", "{", ")", "]", "else", "catch", "while", "?", ":", "&&", "||")

    brace_depth = 0
    paren_depth = 0
    bracket_depth = 0

    for idx, s_line in enumerate(stripped_lines):
        line_num = idx + 1
        s = s_line.strip()
        raw_s = raw_lines[idx].strip() if idx < len(raw_lines) else ""

        if language == "cpp" and s.startswith("#include"):
            # Inspect raw line (comments already not inside #include path in normal code)
            inc_match = re.match(r'^#\s*include\s+(.+)$', raw_s)
            if not inc_match:
                warnings.append({
                    "line": line_num,
                    "type": "malformed_include",
                    "message": f"Malformed #include directive at line {line_num}.",
                })
            else:
                target = re.sub(r"\s*//.*$", "", inc_match.group(1)).strip()
                valid_angle = target.startswith("<") and target.endswith(">") and len(target) > 2
                valid_quote = target.startswith('"') and target.endswith('"') and len(target) > 2
                if not (valid_angle or valid_quote):
                    warnings.append({
                        "line": line_num,
                        "type": "malformed_include",
                        "message": f"Malformed or unclosed #include directive at line {line_num}.",
                    })

        if language == "java" and re.match(r"^(?:package|import)\b", s):
            if not s.endswith(";"):
                warnings.append({
                    "line": line_num,
                    "type": "missing_semicolon",
                    "message": f"Java package/import statement appears to be missing a trailing ';' at line {line_num}.",
                })

        if re.match(
            r"^(?:(?:public|private|protected|abstract|final|static)\s+)*(?:class|struct)\s*\{",
            s,
        ):
            warnings.append({
                "line": line_num,
                "type": "malformed_declaration",
                "message": f"Malformed class/struct declaration missing identifier at line {line_num}.",
            })

        # Update delimiter depths for this line before checking trailing semicolon
        prev_brace_depth = brace_depth
        brace_depth += s.count("{") - s.count("}")
        paren_depth += s.count("(") - s.count(")")
        bracket_depth += s.count("[") - s.count("]")

        # Conservative missing semicolon check on clearly terminated simple statements
        if (
            s
            and prev_brace_depth >= 1
            and paren_depth == 0
            and bracket_depth == 0
            and not s.startswith(("#", "@"))
            and not s.endswith(continuation_endings)
            and not any(re.match(rf"^{re.escape(kw)}(?:\b|\s|$)", s) for kw in control_prefixes)
        ):
            nxt = _next_nonempty_stripped(idx)
            if not any(nxt.startswith(cs) for cs in continuation_starts):
                warnings.append({
                    "line": line_num,
                    "type": "possible_missing_semicolon",
                    "message": f"Possible missing ';' at end of statement on line {line_num}.",
                })

    return warnings


def _analyze_c_family_structure(stripped_code: str) -> Dict[str, Any]:
    """Extract conservative heuristic loop signals for Java/C++ from scanner-stripped code."""
    has_loops = bool(re.search(r"\b(?:for|while)\b", stripped_code))

    # Conservative brace-depth loop tracker
    tokens = re.findall(r"\b(?:for|while|do)\b|[{}();]", stripped_code)
    max_loop_depth = 0
    brace_stack: List[bool] = []
    current_loop_depth = 0
    pending_loop = False
    paren_level = 0
    in_loop_header = False

    for tok in tokens:
        if tok in ("for", "while"):
            pending_loop = True
            in_loop_header = False
        elif tok == "(" and pending_loop and not in_loop_header:
            in_loop_header = True
            paren_level = 1
        elif tok == "(" and in_loop_header:
            paren_level += 1
        elif tok == ")" and in_loop_header:
            paren_level -= 1
            if paren_level == 0:
                in_loop_header = False
        elif tok == "{":
            is_loop = pending_loop and not in_loop_header
            brace_stack.append(is_loop)
            if is_loop:
                current_loop_depth += 1
                if current_loop_depth > max_loop_depth:
                    max_loop_depth = current_loop_depth
            pending_loop = False
        elif tok == "}":
            pending_loop = False
            if brace_stack:
                was_loop = brace_stack.pop()
                if was_loop and current_loop_depth > 0:
                    current_loop_depth -= 1
        elif tok == ";" and pending_loop and not in_loop_header:
            # Single-statement or do-while terminator
            if current_loop_depth + 1 > max_loop_depth:
                max_loop_depth = current_loop_depth + 1
            pending_loop = False

    return {
        "max_loop_depth": max_loop_depth,
        "has_loops": has_loops,
        "has_recursion": None,
        "recursive_functions": [],
        "signal_source": "heuristic_scan",
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
        scan = _scan_c_family(code)
        result["has_syntax_error"] = scan["has_syntax_error"]
        result["syntax_error"] = scan["syntax_error"]
        result["error_line"] = scan["error_line"]
        if scan["has_syntax_error"] and scan["error_line"] is not None:
            result["static_warnings"].append({
                "line": scan["error_line"],
                "type": "syntax_error",
                "message": scan["syntax_error"],
            })
        else:
            stripped_code = scan["stripped_code"]
            result["static_warnings"].extend(
                _collect_c_family_warnings(code, stripped_code, clean_lang)
            )
            result["structural_signals"] = _analyze_c_family_structure(stripped_code)

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

