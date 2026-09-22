"""Read-tool behavior, exercised through the real MCP server via call_tool."""

from fakes import FakeYnab, call, make_server, tool_names

READ_TOOLS = [
    "auth_status",
    "list_plans",
    "list_accounts",
    "list_categories",
    "list_payees",
    "get_transactions",
]


def test_registered_tools_default_read_only():
    names = tool_names(make_server(FakeYnab()))
    assert set(names) == set(READ_TOOLS)


def test_write_tools_registered_only_when_enabled():
    names = tool_names(make_server(FakeYnab(), allow_writes=True))
    assert set(names) == set(READ_TOOLS) | {"create_transaction", "create_transactions"}


def test_auth_status_without_token_makes_no_calls():
    fake = FakeYnab()
    out = call(make_server(fake, token=None), "auth_status")
    assert out["ok"] is False
    assert out["error"] == "no_token"
    assert out["allow_writes"] is False
    assert fake.requests == []


def test_auth_status_ok():
    out = call(make_server(FakeYnab()), "auth_status")
    assert out["ok"] is True
    assert out["user_id"] == "user-1"
    assert out["plans"][0]["name"] == "Test Plan"
    assert out["dedupe_days"] == 10


def test_list_plans():
    out = call(make_server(FakeYnab()), "list_plans")
    assert out["plans"][0]["id"]
    assert out["plans"][0]["currency"] == "USD"


def test_list_accounts_hides_closed_by_default():
    out = call(make_server(FakeYnab()), "list_accounts")
    assert [a["name"] for a in out["accounts"]] == ["Checking", "Credit Card"]
    assert out["accounts"][0]["balance"] == "150"
    out2 = call(make_server(FakeYnab()), "list_accounts", {"include_closed": True})
    assert len(out2["accounts"]) == 3


def test_list_categories_filters():
    out = call(make_server(FakeYnab()), "list_categories")
    names = [c["name"] for c in out["categories"]]
    assert "Coffee" in names
    assert "Legacy Category" not in names
    out2 = call(make_server(FakeYnab()), "list_categories", {"search": "groc"})
    assert [c["name"] for c in out2["categories"]] == ["Groceries"]
    out3 = call(make_server(FakeYnab()), "list_categories", {"include_hidden": True})
    assert "Legacy Category" in [c["name"] for c in out3["categories"]]
    coffee = next(c for c in out["categories"] if c["name"] == "Coffee")
    assert coffee["balance"] == "-2.45"


def test_list_payees_search():
    out = call(make_server(FakeYnab()), "list_payees")
    assert {p["name"] for p in out["payees"]} == {"Starbucks", "Transfer : Credit Card"}
    out2 = call(make_server(FakeYnab()), "list_payees", {"search": "star"})
    assert [p["name"] for p in out2["payees"]] == ["Starbucks"]


def test_get_transactions_sorted_limited():
    out = call(
        make_server(FakeYnab()), "get_transactions", {"account": "Credit Card", "limit": 1}
    )
    assert out["count"] == 1
    assert out["truncated"] is True
    tx = out["transactions"][0]
    assert tx["date"] == "2026-09-18"
    assert tx["amount"] == "-7.45"
    assert tx["amount_milliunits"] == -7450
    assert tx["account"] == "Credit Card"
    assert tx["payee"] == "Starbucks"
    assert tx["category"] == "Coffee"


def test_get_transactions_unapproved_only():
    out = call(make_server(FakeYnab()), "get_transactions", {"unapproved_only": True})
    assert len(out["transactions"]) == 1
    assert all(t["approved"] is False for t in out["transactions"])
    assert out["transactions"][0]["id"] == "t-1"
