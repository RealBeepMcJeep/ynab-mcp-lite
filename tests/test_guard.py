"""The CI guard: this package must never contain a destructive call path.

These tests are the architectural enforcement behind the README promise: the
code can only read and add. If any of these fail, do not weaken them — remove
the offending code instead.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ynab_mcp_lite"

FORBIDDEN_PATTERNS = [
    (r"\.(delete|put|patch)\s*\(", "an HTTP delete/put/patch call"),
    (r"""["'](DELETE|PUT|PATCH)["']""", "a destructive HTTP verb literal"),
    (r"/transactions/import", "the bank-import trigger endpoint"),
    (
        r"""approved["']?\s*[:=]\s*True""",
        "setting approved=True (everything added must stay unapproved)",
    ),
]


def test_no_destructive_calls_anywhere_in_source():
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern, why in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}: {why}")
    assert not offenders, "destructive call sites found:\n" + "\n".join(offenders)


def test_client_public_surface_is_minimal():
    from ynab_mcp_lite.ynab import YnabClient

    public = {name for name in dir(YnabClient) if not name.startswith("_")}
    forbidden = {"delete", "put", "patch", "request", "head", "options"}
    assert not (public & forbidden), f"unexpected public methods: {public & forbidden}"


def test_tool_sets_are_exactly_as_documented():
    from fakes import FakeYnab, make_server, tool_names

    read = {
        "auth_status",
        "list_plans",
        "list_accounts",
        "list_categories",
        "list_payees",
        "get_transactions",
    }
    write = {"create_transaction", "create_transactions"}
    assert set(tool_names(make_server(FakeYnab()))) == read
    assert set(tool_names(make_server(FakeYnab(), allow_writes=True))) == read | write
