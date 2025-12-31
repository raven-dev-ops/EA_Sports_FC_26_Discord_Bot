"""
Scan logging calls for obvious sensitive variable usage.

Usage:
  python -m scripts.check_log_hygiene [paths...]
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

SENSITIVE_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "email",
)

LOG_LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}
LOGGER_NAMES = {"logging", "log", "logger"}
SAFE_CALLS = {"redact_text", "scrub", "redact_ip"}


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(substr in lowered for substr in SENSITIVE_SUBSTRINGS)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _node_has_sensitive_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        func_name = _call_name(node.func)
        if func_name in SAFE_CALLS:
            return False
    if isinstance(node, ast.Name) and _is_sensitive_name(node.id):
        return True
    if isinstance(node, ast.Attribute) and _is_sensitive_name(node.attr):
        return True
    for child in ast.iter_child_nodes(node):
        if _node_has_sensitive_name(child):
            return True
    return False


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in LOG_LEVELS:
        return False
    target = func.value
    return isinstance(target, ast.Name) and target.id in LOGGER_NAMES


def _scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        findings.append(f"{path}:{exc.lineno}:{exc.offset} failed to parse")
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_logging_call(node):
            for arg in node.args:
                if _node_has_sensitive_name(arg):
                    line = getattr(node, "lineno", 0)
                    findings.append(f"{path}:{line} potential sensitive log argument")
                    break
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "paths",
        nargs="*",
        default=["offside_bot", "services", "utils"],
        help="Paths to scan (default: offside_bot, services, utils).",
    )
    args = parser.parse_args()
    findings: list[str] = []
    for raw in args.paths:
        root = Path(raw)
        if root.is_file() and root.suffix == ".py":
            findings.extend(_scan_file(root))
        elif root.is_dir():
            for path in root.rglob("*.py"):
                findings.extend(_scan_file(path))
    if findings:
        print("Log hygiene check failed:")
        for item in sorted(set(findings)):
            print(f"- {item}")
        raise SystemExit(1)
    print("Log hygiene check passed.")


if __name__ == "__main__":
    main()
