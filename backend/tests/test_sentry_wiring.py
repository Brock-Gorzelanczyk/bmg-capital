"""AST/import guards for Sentry SDK wiring — no sentry_sdk import required."""
from __future__ import annotations

import ast
import pathlib

BACKEND_ROOT = pathlib.Path(__file__).parent.parent


def _parse(rel_path: str) -> ast.Module:
    full = BACKEND_ROOT / rel_path
    return ast.parse(full.read_text())


def test_main_imports_sentry_before_app_modules():
    """sentry_sdk must appear before the first 'from app.' import in main.py."""
    tree = _parse("app/main.py")

    sentry_line = None
    first_app_import_line = None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sentry_sdk" and sentry_line is None:
                    sentry_line = node.lineno
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("app.") and first_app_import_line is None:
                first_app_import_line = node.lineno

    assert sentry_line is not None, "import sentry_sdk not found in main.py"
    assert first_app_import_line is not None, "no 'from app.' import found in main.py"
    assert sentry_line < first_app_import_line, (
        f"sentry_sdk imported at line {sentry_line} but first 'from app.' import "
        f"is at line {first_app_import_line} — Sentry must come first"
    )


def test_bot_scheduler_wraps_with_sentry_transaction():
    """_run_and_log must contain all three sentry_sdk calls."""
    source = (BACKEND_ROOT / "strategy_lab/bot_scheduler.py").read_text()

    assert "sentry_sdk.start_transaction" in source, \
        "sentry_sdk.start_transaction not found in bot_scheduler.py"
    assert "sentry_sdk.set_tag" in source, \
        "sentry_sdk.set_tag not found in bot_scheduler.py"
    assert "sentry_sdk.capture_exception" in source, \
        "sentry_sdk.capture_exception not found in bot_scheduler.py"

    # Also confirm they live inside _run_and_log (not some other function)
    tree = _parse("strategy_lab/bot_scheduler.py")
    run_and_log_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_and_log":
            run_and_log_node = node
            break

    assert run_and_log_node is not None, "_run_and_log function not found in bot_scheduler.py"

    func_source_lines = (BACKEND_ROOT / "strategy_lab/bot_scheduler.py").read_text().splitlines()
    # Extract lines belonging to the function (from its start to the next top-level def/class)
    func_lines = []
    in_func = False
    for i, line in enumerate(func_source_lines, start=1):
        if i == run_and_log_node.lineno:
            in_func = True
        if in_func:
            if i > run_and_log_node.lineno and line and not line[0].isspace() and not line.startswith("#"):
                break
            func_lines.append(line)

    func_text = "\n".join(func_lines)
    assert "sentry_sdk.start_transaction" in func_text, \
        "sentry_sdk.start_transaction not inside _run_and_log"
    assert "sentry_sdk.set_tag" in func_text, \
        "sentry_sdk.set_tag not inside _run_and_log"
    assert "sentry_sdk.capture_exception" in func_text, \
        "sentry_sdk.capture_exception not inside _run_and_log"


def test_sentry_test_endpoint_exists():
    """admin.py must have @router.post('/sentry-test') and raise ValueError."""
    tree = _parse("app/routers/admin.py")

    sentry_test_func = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "sentry_test":
            continue
        # Check for @router.post("/sentry-test") decorator
        for deco in node.decorator_list:
            if (
                isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Attribute)
                and deco.func.attr == "post"
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
                and deco.args[0].value == "/sentry-test"
            ):
                sentry_test_func = node
                break
        if sentry_test_func:
            break

    assert sentry_test_func is not None, \
        "@router.post('/sentry-test') decorated function not found in admin.py"

    # Confirm the function body contains a raise ValueError
    raises = [
        node for node in ast.walk(sentry_test_func)
        if isinstance(node, ast.Raise)
        and node.exc is not None
        and (
            (isinstance(node.exc, ast.Call)
             and isinstance(node.exc.func, ast.Name)
             and node.exc.func.id == "ValueError")
        )
    ]
    assert raises, "sentry_test endpoint must raise ValueError"
