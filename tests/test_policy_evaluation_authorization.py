"""Regression tests for policy-evaluation subscription authorization."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTES = PROJECT_ROOT / "client" / "routes.py"


def _decorator_names(function):
    names = []
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Name):
            names.append(decorator.id)
        elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
            argument = decorator.args[0].value if decorator.args and isinstance(decorator.args[0], ast.Constant) else None
            names.append((decorator.func.id, argument))
    return names


def test_policy_evaluation_post_routes_require_subscription():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in ("policy_evaluation_results", "policy_evaluation_batch"):
        decorators = _decorator_names(functions[name])
        assert "login_required" in decorators
        assert ("subscription_required", "policy_evaluation") in decorators
