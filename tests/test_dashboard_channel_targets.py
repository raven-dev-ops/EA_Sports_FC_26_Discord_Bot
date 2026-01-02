import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fields_by_function(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    visitor = _ResolveChannelVisitor()
    visitor.visit(tree)
    return visitor.fields_by_function


class _ResolveChannelVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._stack: list[str] = []
        self.fields_by_function: dict[str, set[str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if _is_resolve_channel_call(node):
            field = _extract_field_literal(node)
            if field:
                func_name = self._stack[-1] if self._stack else "<module>"
                self.fields_by_function.setdefault(func_name, set()).add(field)
        self.generic_visit(node)


def _is_resolve_channel_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == "resolve_channel_id"
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == "resolve_channel_id"
    return False


def _extract_field_literal(node: ast.Call) -> str | None:
    for keyword in node.keywords:
        if keyword.arg != "field":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _extract_listing_spec_fields(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fields: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id != "listing_specs":
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            for element in node.value.elts:
                if not isinstance(element, (ast.List, ast.Tuple)):
                    continue
                if not element.elts:
                    continue
                head = element.elts[0]
                if isinstance(head, ast.Constant) and isinstance(head.value, str):
                    fields.add(head.value)
    return fields


def test_portal_buttons_use_expected_channel_fields() -> None:
    expectations = {
        "interactions/admin_portal.py": {
            "on_managers": {"channel_manager_portal_id"},
            "send_admin_portal_message": {"channel_staff_portal_id"},
            "post_admin_portal": {"channel_staff_portal_id"},
        },
        "interactions/manager_portal.py": {
            "post_manager_portal": {"channel_manager_portal_id"},
        },
        "interactions/coach_portal.py": {
            "send_coach_portal_message": {"channel_coach_portal_id"},
            "post_coach_portal": {"channel_coach_portal_id"},
        },
        "interactions/recruit_portal.py": {
            "post_recruit_portal": {"channel_recruit_portal_id"},
        },
        "interactions/listing_instructions.py": {
            "post_listing_channel_instructions": {
                "channel_coach_portal_id",
                "channel_recruit_portal_id",
                "channel_manager_portal_id",
            },
        },
        "interactions/views.py": {
            "_handle_decision": {"channel_club_listing_id"},
        },
    }

    for rel_path, func_expectations in expectations.items():
        fields_by_function = _fields_by_function(REPO_ROOT / rel_path)
        for func_name, expected in func_expectations.items():
            actual = fields_by_function.get(func_name)
            assert actual == expected, f"{rel_path}:{func_name} -> {actual} (expected {expected})"


def test_listing_instruction_fields_match_expected_channels() -> None:
    fields = _extract_listing_spec_fields(REPO_ROOT / "interactions/listing_instructions.py")
    assert fields == {
        "channel_recruit_listing_id",
        "channel_club_listing_id",
        "channel_premium_coaches_id",
    }
