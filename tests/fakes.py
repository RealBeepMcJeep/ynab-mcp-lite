"""Fake YNAB API for tests — routed through httpx.MockTransport. No network."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ynab_mcp_lite.config import Settings
from ynab_mcp_lite.server import create_server
from ynab_mcp_lite.ynab import YnabClient

PLAN_ID = "11111111-1111-1111-1111-111111111111"
ACCT_CHECKING = "22222222-2222-2222-2222-222222222222"
ACCT_CARD = "33333333-3333-3333-3333-333333333333"
PAYEE_STARBUCKS = "44444444-4444-4444-4444-444444444444"
CAT_COFFEE = "55555555-5555-5555-5555-555555555555"
CAT_GROCERIES = "66666666-6666-6666-6666-666666666666"
CAT_HIDDEN = "77777777-7777-7777-7777-777777777777"


def plan_summary() -> dict[str, Any]:
    return {
        "id": PLAN_ID,
        "name": "Test Plan",
        "last_modified_on": "2026-09-20T00:00:00+00:00",
        "first_month": "2026-01-01",
        "last_month": "2026-10-01",
        "currency_format": {"iso_code": "USD"},
    }


def plan_detail() -> dict[str, Any]:
    return {
        "id": PLAN_ID,
        "name": "Test Plan",
        "last_modified_on": "2026-09-20T00:00:00+00:00",
        "currency_format": {"iso_code": "USD"},
        "accounts": [
            {
                "id": ACCT_CHECKING,
                "name": "Checking",
                "type": "checking",
                "on_budget": True,
                "closed": False,
                "deleted": False,
                "balance": 150000,
            },
            {
                "id": ACCT_CARD,
                "name": "Credit Card",
                "type": "creditCard",
                "on_budget": True,
                "closed": False,
                "deleted": False,
                "balance": -23000,
            },
            {
                "id": "88888888-8888-8888-8888-888888888888",
                "name": "Old Savings",
                "type": "savings",
                "on_budget": False,
                "closed": True,
                "deleted": False,
                "balance": 1,
            },
        ],
        "payees": [
            {"id": PAYEE_STARBUCKS, "name": "Starbucks", "deleted": False},
            {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "name": "Transfer : Credit Card",
                "deleted": False,
                "transfer_account_id": ACCT_CARD,
            },
            {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "name": "Deleted Payee", "deleted": True},
        ],
        "categories": [
            {
                "id": CAT_COFFEE,
                "category_group_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "category_group_name": "Everyday",
                "name": "Coffee",
                "hidden": False,
                "internal": False,
                "deleted": False,
                "budgeted": 5000,
                "activity": -7450,
                "balance": -2450,
            },
            {
                "id": CAT_GROCERIES,
                "category_group_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "category_group_name": "Everyday",
                "name": "Groceries",
                "hidden": False,
                "internal": False,
                "deleted": False,
                "budgeted": 60000,
                "activity": -42000,
                "balance": 18000,
            },
            {
                "id": CAT_HIDDEN,
                "category_group_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "category_group_name": "Old Stuff",
                "name": "Legacy Category",
                "hidden": True,
                "internal": False,
                "deleted": False,
                "budgeted": 0,
                "activity": 0,
                "balance": 0,
            },
        ],
        "category_groups": [
            {
                "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "name": "Everyday",
                "hidden": False,
                "internal": False,
                "deleted": False,
            },
            {
                "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "name": "Old Stuff",
                "hidden": True,
                "internal": False,
                "deleted": False,
            },
        ],
    }


def transaction(
    tx_id: str,
    account_id: str = ACCT_CARD,
    tx_date: str = "2026-09-18",
    amount: int = -7450,
    payee_id: str | None = PAYEE_STARBUCKS,
    category_id: str | None = CAT_COFFEE,
    approved: bool = True,
    memo: str | None = None,
    deleted: bool = False,
) -> dict[str, Any]:
    return {
        "id": tx_id,
        "date": tx_date,
        "amount": amount,
        "memo": memo,
        "cleared": "cleared",
        "approved": approved,
        "flag_color": None,
        "flag_name": None,
        "account_id": account_id,
        "payee_id": payee_id,
        "category_id": category_id,
        "transfer_account_id": None,
        "transfer_transaction_id": None,
        "matched_transaction_id": None,
        "import_id": None,
        "deleted": deleted,
    }


class FakeYnab:
    """Callable httpx.MockTransport handler that mimics the YNAB API."""

    def __init__(self, *, token: str = "tok-test") -> None:
        self.token = token
        self.requests: list[httpx.Request] = []
        self.created: list[dict[str, Any]] = []
        self.transactions: list[dict[str, Any]] = [
            transaction("t-1", tx_date="2026-09-18", amount=-7450, approved=False),
            transaction(
                "t-2",
                tx_date="2026-09-15",
                amount=-2300,
                payee_id=None,
                category_id=None,
                approved=True,
                memo="lunch",
            ),
        ]
        self._next_id = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        auth = request.headers.get("authorization", "")
        if not auth.replace("Bearer ", "").strip():
            return httpx.Response(
                401, json={"error": {"name": "unauthorized", "detail": "Unauthorized"}}
            )
        path = request.url.path
        method = request.method

        if path == "/v1/user":
            return httpx.Response(200, json={"data": {"user": {"id": "user-1"}}})
        if path == "/v1/plans":
            return httpx.Response(200, json={"data": {"plans": [plan_summary()]}})
        if path == f"/v1/plans/{PLAN_ID}" and method == "GET":
            return httpx.Response(
                200, json={"data": {"plan": plan_detail(), "server_knowledge": 7}}
            )
        if path == f"/v1/plans/{PLAN_ID}/transactions" and method == "GET":
            return httpx.Response(200, json={"data": {"transactions": self._filter(request)}})
        if path.startswith(f"/v1/plans/{PLAN_ID}/accounts/") and method == "GET":
            return httpx.Response(200, json={"data": {"transactions": self._filter(request)}})
        if path == f"/v1/plans/{PLAN_ID}/transactions" and method == "POST":
            return self._create(request)
        return httpx.Response(404, json={"error": {"name": "not_found", "detail": path}})

    def _filter(self, request: httpx.Request) -> list[dict[str, Any]]:
        txs = [t for t in self.transactions if not t.get("deleted")]
        path = request.url.path
        if "/accounts/" in path:
            acct = path.split("/accounts/")[1].split("/")[0]
            txs = [t for t in txs if t["account_id"] == acct]
        since = request.url.params.get("since_date")
        if since:
            txs = [t for t in txs if t["date"] >= since]
        until = request.url.params.get("until_date")
        if until:
            txs = [t for t in txs if t["date"] <= until]
        if request.url.params.get("type") == "unapproved":
            txs = [t for t in txs if not t["approved"]]
        return txs

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        single = body.get("transaction")
        items = [single] if single else list(body.get("transactions") or [])
        accounts_map = {a["id"]: a["name"] for a in plan_detail()["accounts"]}
        payees_map = {p["id"]: p["name"] for p in plan_detail()["payees"]}
        cats_map = {c["id"]: c["name"] for c in plan_detail()["categories"]}
        created = []
        for item in items:
            self.created.append(item)
            self._next_id += 1
            tx = transaction(
                f"new-{self._next_id}",
                account_id=item["account_id"],
                tx_date=item["date"],
                amount=item["amount"],
                payee_id=item.get("payee_id"),
                category_id=item.get("category_id"),
                approved=item.get("approved", False),
                memo=item.get("memo"),
            )
            tx["cleared"] = item.get("cleared", "uncleared")
            tx["account_name"] = accounts_map.get(tx["account_id"])
            if item.get("payee_name"):
                tx["payee_id"] = None
                tx["payee_name"] = item["payee_name"]
            elif tx.get("payee_id"):
                tx["payee_name"] = payees_map.get(tx["payee_id"])
            if tx.get("category_id"):
                tx["category_name"] = cats_map.get(tx["category_id"])
            self.transactions.append(tx)
            created.append(tx)
        data: dict[str, Any] = {
            "transaction_ids": [t["id"] for t in created],
            "server_knowledge": 8,
        }
        if single:
            data["transaction"] = created[0]
        else:
            data["transactions"] = created
        return httpx.Response(201, json={"data": data})


def make_settings(
    *, token: str | None = "tok-test", allow_writes: bool = False, **overrides: Any
) -> Settings:
    defaults: dict[str, Any] = {
        "default_plan_id": None,
        "dedupe_days": 10,
        "allowed_hosts": ("test",),
        "base_url": "https://api.ynab.com/v1",
    }
    defaults.update(overrides)
    return Settings(token=token, allow_writes=allow_writes, **defaults)


def make_server(fake: FakeYnab, *, allow_writes: bool = False, token: str | None = "tok-test"):
    settings = make_settings(token=token, allow_writes=allow_writes)

    def factory() -> YnabClient:
        return YnabClient(
            token=fake.token,
            base_url="https://api.ynab.com/v1",
            transport=httpx.MockTransport(fake),
        )

    return create_server(settings, client_factory=factory)


def call(server, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    import asyncio

    result = asyncio.run(server.call_tool(name, args or {}))
    text = result.content[0].text if result.content else ""
    return json.loads(text)


def tool_names(server) -> list[str]:
    import asyncio

    return [t.name for t in asyncio.run(server.list_tools())]
