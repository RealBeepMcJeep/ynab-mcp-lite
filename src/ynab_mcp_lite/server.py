"""The MCP tool surface — six reads, plus two add-only writes when enabled.

Design limits enforced here (see README):

* Reads: plans, accounts, categories, payees, transactions, auth status.
* Writes exist only when ``YNAB_ALLOW_WRITES=1`` (in a deployment that is a
  deliberate, separate step). They can only ADD transactions; everything
  added is unapproved and every write tool is dry-run by default.
* No tool can update, delete, approve, or trigger an import — there is no
  code path for it anywhere in this package.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .config import Settings
from .ynab import (
    FLAG_COLORS,
    ResolveError,
    YnabClient,
    YnabError,
    amount_to_milliunits,
    apply_names,
    find_amount_matches,
    flatten_categories,
    milliunits_to_amount,
    parse_amount,
    parse_date,
    resolve_one,
    trim_transaction,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True)
ADD_ONLY_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)


def build_transport_security(settings: Settings) -> TransportSecuritySettings:
    """Host allowlist for the HTTP transport (DNS-rebinding protection).

    The middleware matches Host headers exactly, with ``<host>:*`` allowing
    any port — hence the container name appears both bare and with ``:*``.
    Without this, a request arriving as ``Host: ynab-mcp-lite:8000`` would be
    rejected with 421 even though it is exactly the client we want.
    """
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=[
            "http://ynab-mcp-lite:*",
            "http://localhost:*",
            "http://127.0.0.1:*",
        ],
    )


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def create_server(
    settings: Settings | None = None,
    *,
    client_factory: Callable[[], YnabClient] | None = None,
) -> MCPServer:
    settings = settings or Settings.from_env()
    server = MCPServer(
        name="ynab-mcp-lite",
        title="YNAB (read-first, add-only)",
        description="Deliberately tiny, non-destructive MCP server for YNAB.",
        instructions=(
            "Reads are always available. This server can only ADD transactions, and "
            "only when explicitly enabled; anything it adds is unapproved and every "
            "write tool is dry-run by default. It can never update, delete, or "
            "approve anything in YNAB."
        ),
        version=__version__,
    )

    # ------------------------------------------------------------------ internals

    def _new_client() -> YnabClient:
        if client_factory is not None:
            return client_factory()
        return YnabClient(token=settings.token, base_url=settings.base_url)

    def _as_dict(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, (YnabError, ResolveError)):
            return exc.to_dict()
        return {"error": "invalid_input", "message": str(exc)}

    def _fail(exc: Exception) -> str:
        return _json(_as_dict(exc))

    def _token_guard() -> str | None:
        if not settings.token:
            return _json(
                {
                    "error": "no_token",
                    "message": (
                        "YNAB_API_TOKEN is not set in the environment, so no calls "
                        "can be made to YNAB. Configure it (stack .env) and restart."
                    ),
                }
            )
        return None

    def _writes_guard() -> str | None:
        if not settings.allow_writes:
            return _json(
                {
                    "error": "writes_disabled",
                    "message": "Writes are disabled (YNAB_ALLOW_WRITES is not enabled).",
                }
            )
        return _token_guard()

    def _fetch_plan_detail(client: YnabClient, plan_id: str) -> dict[str, Any]:
        return client.get(f"/plans/{plan_id}")["data"]["plan"]

    def _plan_ref(plan: dict[str, Any]) -> dict[str, Any]:
        return {"id": plan.get("id"), "name": plan.get("name")}

    def _pick_plan(client: YnabClient, plan_ref: str | None) -> dict[str, Any]:
        plans = client.get("/plans")["data"]["plans"]
        ref = (plan_ref or settings.default_plan_id or "").strip() or None
        if ref is None:
            if len(plans) == 1:
                return plans[0]
            raise ResolveError(
                "plan",
                "",
                f"no plan specified and {len(plans)} plans exist — pass plan=<name or id> "
                "or set YNAB_PLAN_ID",
                failure="empty",
                candidates=[{"id": p.get("id"), "name": p.get("name")} for p in plans],
            )
        return resolve_one("plan", plans, ref)

    def _name_maps(
        detail: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        accounts = {a.get("id"): a.get("name") for a in detail.get("accounts") or []}
        payees = {p.get("id"): p.get("name") for p in detail.get("payees") or []}
        categories = {c.get("id"): c.get("name") for c in flatten_categories(detail)}
        return accounts, payees, categories

    # ------------------------------------------------------------------ reads

    @server.tool(
        description=(
            "Check the YNAB connection: token validity, plan list, and this server's "
            "configuration (writes on/off, dedupe window). Never returns the token."
        ),
        annotations=READ_ONLY,
    )
    def auth_status() -> str:
        base = {
            "allow_writes": settings.allow_writes,
            "default_plan_id": settings.default_plan_id,
            "dedupe_days": settings.dedupe_days,
            "version": __version__,
        }
        if not settings.token:
            return _json(
                {
                    **base,
                    "ok": False,
                    "error": "no_token",
                    "message": "YNAB_API_TOKEN is not set; no calls can be made to YNAB.",
                }
            )
        try:
            with _new_client() as client:
                user = client.get("/user")["data"]["user"]
                plans = client.get("/plans")["data"]["plans"]
        except YnabError as exc:
            return _json({**base, "ok": False, **exc.to_dict()})
        return _json(
            {
                **base,
                "ok": True,
                "user_id": user.get("id"),
                "plans": [{"id": p.get("id"), "name": p.get("name")} for p in plans],
            }
        )

    @server.tool(
        description=(
            "List the plans (budgets) on this YNAB account: id, name, last month, "
            "currency."
        ),
        annotations=READ_ONLY,
    )
    def list_plans() -> str:
        guard = _token_guard()
        if guard:
            return guard
        try:
            with _new_client() as client:
                plans = client.get("/plans")["data"]["plans"]
        except YnabError as exc:
            return _fail(exc)
        return _json(
            {
                "default_plan_id": settings.default_plan_id,
                "plans": [
                    {
                        "id": p.get("id"),
                        "name": p.get("name"),
                        "last_modified_on": p.get("last_modified_on"),
                        "last_month": p.get("last_month"),
                        "currency": (p.get("currency_format") or {}).get("iso_code"),
                    }
                    for p in plans
                ],
            }
        )

    @server.tool(
        description=(
            "List accounts in a plan: id, name, type, on-budget flag, balance. Closed "
            "accounts are hidden unless include_closed=true."
        ),
        annotations=READ_ONLY,
    )
    def list_accounts(plan: str | None = None, include_closed: bool = False) -> str:
        guard = _token_guard()
        if guard:
            return guard
        try:
            with _new_client() as client:
                picked = _pick_plan(client, plan)
                detail = _fetch_plan_detail(client, picked["id"])
        except (YnabError, ResolveError, ValueError) as exc:
            return _fail(exc)
        accounts = []
        for account in detail.get("accounts") or []:
            if account.get("deleted"):
                continue
            if account.get("closed") and not include_closed:
                continue
            accounts.append(
                {
                    "id": account.get("id"),
                    "name": account.get("name"),
                    "type": account.get("type"),
                    "on_budget": account.get("on_budget"),
                    "closed": account.get("closed"),
                    "balance": milliunits_to_amount(int(account.get("balance") or 0)),
                }
            )
        return _json({"plan": _plan_ref(picked), "accounts": accounts})

    @server.tool(
        description=(
            "List categories in a plan: id, group, name, and budgeted/activity/balance "
            "for the current month. Hidden categories are excluded unless "
            "include_hidden=true; search matches name or group (substring)."
        ),
        annotations=READ_ONLY,
    )
    def list_categories(
        plan: str | None = None,
        search: str | None = None,
        include_hidden: bool = False,
    ) -> str:
        guard = _token_guard()
        if guard:
            return guard
        try:
            with _new_client() as client:
                picked = _pick_plan(client, plan)
                detail = _fetch_plan_detail(client, picked["id"])
        except (YnabError, ResolveError, ValueError) as exc:
            return _fail(exc)
        cats = flatten_categories(detail)
        if not include_hidden:
            cats = [c for c in cats if not c.get("hidden")]
        if search:
            needle = search.strip().lower()
            cats = [
                c
                for c in cats
                if needle in str(c.get("name") or "").lower()
                or needle in str(c.get("_group") or "").lower()
            ]
        out = [
            {
                "id": c.get("id"),
                "group": c.get("_group"),
                "name": c.get("name"),
                "budgeted": milliunits_to_amount(int(c.get("budgeted") or 0)),
                "activity": milliunits_to_amount(int(c.get("activity") or 0)),
                "balance": milliunits_to_amount(int(c.get("balance") or 0)),
                "hidden": bool(c.get("hidden")),
            }
            for c in cats
        ]
        return _json({"plan": _plan_ref(picked), "count": len(out), "categories": out})

    @server.tool(
        description=(
            "List payees in a plan: id, name, and the transfer target account for "
            "transfer payees. search matches the name (substring)."
        ),
        annotations=READ_ONLY,
    )
    def list_payees(plan: str | None = None, search: str | None = None) -> str:
        guard = _token_guard()
        if guard:
            return guard
        try:
            with _new_client() as client:
                picked = _pick_plan(client, plan)
                detail = _fetch_plan_detail(client, picked["id"])
        except (YnabError, ResolveError, ValueError) as exc:
            return _fail(exc)
        payees = []
        for payee in detail.get("payees") or []:
            if payee.get("deleted"):
                continue
            if search and search.strip().lower() not in str(payee.get("name") or "").lower():
                continue
            payees.append(
                {
                    "id": payee.get("id"),
                    "name": payee.get("name"),
                    "transfer_account_id": payee.get("transfer_account_id"),
                }
            )
        return _json({"plan": _plan_ref(picked), "count": len(payees), "payees": payees})

    @server.tool(
        description=(
            "List transactions, newest first. Optional filters: one account, a date "
            "range (YYYY-MM-DD, inclusive), or only unapproved. Returns dollar amounts "
            "as strings plus exact milliunits. limit caps the rows returned (max 500)."
        ),
        annotations=READ_ONLY,
    )
    def get_transactions(
        plan: str | None = None,
        account: str | None = None,
        since_date: str | None = None,
        until_date: str | None = None,
        unapproved_only: bool = False,
        limit: int = 100,
    ) -> str:
        guard = _token_guard()
        if guard:
            return guard
        try:
            limit_n = max(1, min(int(limit), 500))
            params: dict[str, Any] = {}
            if since_date:
                params["since_date"] = parse_date(since_date).isoformat()
            if until_date:
                params["until_date"] = parse_date(until_date).isoformat()
            if unapproved_only:
                params["type"] = "unapproved"
            with _new_client() as client:
                picked = _pick_plan(client, plan)
                detail = _fetch_plan_detail(client, picked["id"])
                account_obj = None
                if account:
                    account_obj = resolve_one(
                        "account", detail.get("accounts") or [], account
                    )
                if account_obj is not None:
                    path = f"/plans/{picked['id']}/accounts/{account_obj['id']}/transactions"
                else:
                    path = f"/plans/{picked['id']}/transactions"
                transactions = client.get(path, params=params)["data"]["transactions"]
                accounts_map, payees_map, categories_map = _name_maps(detail)
        except (YnabError, ResolveError, ValueError, TypeError) as exc:
            return _fail(exc)

        if unapproved_only:
            transactions = [t for t in transactions if not t.get("approved")]
        transactions.sort(
            key=lambda t: (str(t.get("date") or ""), t.get("amount") or 0), reverse=True
        )
        total = len(transactions)
        shown = transactions[:limit_n]
        return _json(
            {
                "plan": _plan_ref(picked),
                "account": (
                    {"id": account_obj["id"], "name": account_obj.get("name")}
                    if account_obj is not None
                    else None
                ),
                "count": len(shown),
                "total_matching": total,
                "truncated": total > len(shown),
                "transactions": [
                    trim_transaction(apply_names(t, accounts_map, payees_map, categories_map))
                    for t in shown
                ],
            }
        )

    # ------------------------------------------------------------------ writes

    def _parse_flag(flag_color: str | None) -> str | None:
        if flag_color is None:
            return None
        flag = str(flag_color).strip().lower()
        if not flag:
            return None
        if flag not in FLAG_COLORS:
            raise ValueError(
                f"flag_color must be one of {sorted(FLAG_COLORS)} (or omitted)"
            )
        return flag

    def _resolve_payee_spec(
        detail: dict[str, Any], payee_ref: str | None
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        """Returns (payee_obj, note, passthrough_name)."""
        if payee_ref is None or not str(payee_ref).strip():
            return None, None, None
        ref = str(payee_ref).strip()
        try:
            return resolve_one("payee", detail.get("payees") or [], ref), None, None
        except ResolveError as exc:
            if exc.failure == "not_found":
                if len(ref) > 200:
                    raise ValueError("payee name exceeds 200 characters") from exc
                note = "payee not found among existing payees — YNAB will match by name or create it"
                return (None, note, ref)
            raise

    def _prepare_transaction(
        item: dict[str, Any],
        detail: dict[str, Any],
        accounts: list[dict[str, Any]],
        categories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not item.get("account"):
            raise ValueError("account is required")
        if not item.get("date"):
            raise ValueError("date is required (YYYY-MM-DD)")
        if item.get("amount") is None or str(item.get("amount")).strip() == "":
            raise ValueError("amount is required (dollars, e.g. -12.34)")

        date_obj = parse_date(str(item["date"]))
        amount_mu = amount_to_milliunits(parse_amount(item["amount"]))
        flag = _parse_flag(item.get("flag_color"))
        memo = (str(item.get("memo")).strip() if item.get("memo") is not None else "") or None
        if memo and len(memo) > 500:
            raise ValueError("memo exceeds 500 characters")

        account = resolve_one("account", accounts, str(item["account"]))
        payee_obj, payee_note, payee_pass = _resolve_payee_spec(detail, item.get("payee"))
        category_obj = None
        if item.get("category"):
            category_obj = resolve_one("category", categories, str(item["category"]))

        payload: dict[str, Any] = {
            "account_id": account["id"],
            "date": date_obj.isoformat(),
            "amount": amount_mu,
            "approved": False,  # forced: everything added is unapproved
            "cleared": "uncleared",  # forced: never claim a bank-cleared state
        }
        if payee_obj is not None:
            payload["payee_id"] = payee_obj["id"]
        elif payee_pass:
            payload["payee_name"] = payee_pass
        if category_obj is not None:
            payload["category_id"] = category_obj["id"]
        if memo:
            payload["memo"] = memo
        if flag:
            payload["flag_color"] = flag

        preview = {
            "account": {"id": account["id"], "name": account.get("name")},
            "date": date_obj.isoformat(),
            "amount": milliunits_to_amount(amount_mu),
            "payee": (
                {"id": payee_obj["id"], "name": payee_obj.get("name")}
                if payee_obj is not None
                else ({"name": payee_pass, "new": True} if payee_pass else None)
            ),
            "category": (
                {"id": category_obj["id"], "name": category_obj.get("name")}
                if category_obj is not None
                else None
            ),
            "memo": memo,
            "flag_color": flag,
            "approved": False,
            "cleared": "uncleared",
        }
        if payee_note:
            preview["payee_note"] = payee_note

        return {
            "payload": payload,
            "preview": preview,
            "date_obj": date_obj,
            "amount_mu": amount_mu,
        }

    def _duplicate_matches(
        client: YnabClient,
        plan_id: str,
        account_id: str,
        amount_mu: int,
        tx_date: date,
        cache: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        since = (tx_date - timedelta(days=settings.dedupe_days)).isoformat()
        key = f"{account_id}|{since}"
        if cache is not None and key in cache:
            recent = cache[key]
        else:
            recent = client.get(
                f"/plans/{plan_id}/accounts/{account_id}/transactions",
                params={"since_date": since},
            )["data"]["transactions"]
            if cache is not None:
                cache[key] = recent
        return find_amount_matches(recent, amount_mu, tx_date, settings.dedupe_days)

    if settings.allow_writes:

        @server.tool(
            description=(
                "Add ONE transaction to YNAB — the only write this server can perform. "
                "SAFETY: dry_run defaults to true; re-call with dry_run=false after "
                "reviewing the preview. Created transactions are ALWAYS unapproved — "
                "nothing affects the budget until approved in the YNAB app. A duplicate "
                "pre-check refuses entries matching an existing amount within "
                "±YNAB_DEDUPE_DAYS unless allow_duplicate=true. amount is in dollars "
                "(e.g. -12.34); account/payee/category accept a name or id; a payee name "
                "that does not exist yet is passed through so YNAB can create it."
            ),
            annotations=ADD_ONLY_WRITE,
        )
        def create_transaction(
            account: str,
            date: str,
            amount: str | float,
            plan: str | None = None,
            payee: str | None = None,
            category: str | None = None,
            memo: str | None = None,
            flag_color: str | None = None,
            dry_run: bool = True,
            allow_duplicate: bool = False,
        ) -> str:
            guard = _writes_guard()
            if guard:
                return guard
            result: dict[str, Any] = {}
            try:
                with _new_client() as client:
                    picked = _pick_plan(client, plan)
                    detail = _fetch_plan_detail(client, picked["id"])
                    accounts = detail.get("accounts") or []
                    categories = flatten_categories(detail)
                    prepared = _prepare_transaction(
                        {
                            "account": account,
                            "date": date,
                            "amount": amount,
                            "payee": payee,
                            "category": category,
                            "memo": memo,
                            "flag_color": flag_color,
                        },
                        detail,
                        accounts,
                        categories,
                    )
                    matches = _duplicate_matches(
                        client,
                        picked["id"],
                        prepared["payload"]["account_id"],
                        prepared["amount_mu"],
                        prepared["date_obj"],
                    )
                    if matches and not allow_duplicate:
                        accounts_map, payees_map, categories_map = _name_maps(detail)
                        return _json(
                            {
                                "error": "possible_duplicate",
                                "message": (
                                    f"{len(matches)} existing transaction(s) in this account "
                                    f"have the same amount within ±{settings.dedupe_days} "
                                    "days. Not creating. Review the matches; if this is "
                                    "genuinely a separate charge, re-call with "
                                    "allow_duplicate=true."
                                ),
                                "matches": [
                                    trim_transaction(
                                        apply_names(m, accounts_map, payees_map, categories_map)
                                    )
                                    for m in matches[:10]
                                ],
                            }
                        )
                    if dry_run:
                        return _json(
                            {
                                "dry_run": True,
                                "would_create": prepared["preview"],
                                "duplicate_check": "overridden" if matches else "clear",
                                "note": "Nothing was written. Re-call with dry_run=false "
                                "to create it.",
                            }
                        )
                    response = client.post(
                        f"/plans/{picked['id']}/transactions",
                        {"transaction": prepared["payload"]},
                    )
                    created = response["data"].get("transaction")
                    result = {
                        "dry_run": False,
                        "created": trim_transaction(created) if created else None,
                        "transaction_ids": (
                            None if created else response["data"].get("transaction_ids")
                        ),
                        "note": "Created UNAPPROVED — review and approve it in the YNAB "
                        "app when ready.",
                    }
            except (YnabError, ResolveError, ValueError, TypeError) as exc:
                return _fail(exc)
            return _json(result)

        @server.tool(
            description=(
                "Add MULTIPLE transactions in one call (statement/reconciliation runs, "
                "max 50). Each item: {account, date, amount (dollars), payee?, "
                "category?, memo?, flag_color?}. Same safety model as "
                "create_transaction: dry_run defaults to true; created items are ALWAYS "
                "unapproved; a duplicate pre-check runs per item. ALL items are "
                "validated first — if anything fails, nothing is created."
            ),
            annotations=ADD_ONLY_WRITE,
        )
        def create_transactions(
            transactions: list[dict[str, Any]],
            plan: str | None = None,
            dry_run: bool = True,
            allow_duplicate: bool = False,
        ) -> str:
            guard = _writes_guard()
            if guard:
                return guard
            result: dict[str, Any] = {}
            try:
                if not transactions:
                    raise ValueError("transactions list is empty")
                if len(transactions) > 50:
                    raise ValueError("at most 50 transactions per batch")
                with _new_client() as client:
                    picked = _pick_plan(client, plan)
                    detail = _fetch_plan_detail(client, picked["id"])
                    accounts = detail.get("accounts") or []
                    categories = flatten_categories(detail)

                    prepared: list[dict[str, Any]] = []
                    errors: list[dict[str, Any]] = []
                    for index, item in enumerate(transactions):
                        try:
                            prep = _prepare_transaction(item, detail, accounts, categories)
                            prep["index"] = index
                            prepared.append(prep)
                        except (ResolveError, ValueError, TypeError) as exc:
                            errors.append({"index": index, "input": item, **_as_dict(exc)})
                    if errors:
                        return _json(
                            {
                                "error": "validation_failed",
                                "message": "Nothing was created — fix these items and retry.",
                                "items": errors,
                            }
                        )

                    cache: dict[str, list[dict[str, Any]]] = {}
                    duplicates: list[dict[str, Any]] = []
                    for prep in prepared:
                        matches = _duplicate_matches(
                            client,
                            picked["id"],
                            prep["payload"]["account_id"],
                            prep["amount_mu"],
                            prep["date_obj"],
                            cache,
                        )
                        if matches:
                            duplicates.append(
                                {
                                    "index": prep["index"],
                                    "matches": [trim_transaction(m) for m in matches[:5]],
                                }
                            )
                    if duplicates and not allow_duplicate:
                        return _json(
                            {
                                "error": "possible_duplicate",
                                "message": (
                                    f"{len(duplicates)} item(s) match existing transactions "
                                    f"within ±{settings.dedupe_days} days. Nothing was "
                                    "created. Review; if genuinely distinct, re-call with "
                                    "allow_duplicate=true."
                                ),
                                "duplicates": duplicates,
                            }
                        )

                    if dry_run:
                        return _json(
                            {
                                "dry_run": True,
                                "count": len(prepared),
                                "would_create": [prep["preview"] for prep in prepared],
                                "duplicate_check": "overridden" if duplicates else "clear",
                                "note": "Nothing was written. Re-call with dry_run=false "
                                "to create them.",
                            }
                        )

                    response = client.post(
                        f"/plans/{picked['id']}/transactions",
                        {"transactions": [prep["payload"] for prep in prepared]},
                    )
                    data = response["data"]
                    created = data.get("transactions") or []
                    result = {
                        "dry_run": False,
                        "created_count": len(created),
                        "created": [trim_transaction(t) for t in created],
                        "transaction_ids": data.get("transaction_ids"),
                        "duplicate_import_ids": data.get("duplicate_import_ids") or [],
                        "note": "All created UNAPPROVED — review and approve them in the "
                        "YNAB app.",
                    }
            except (YnabError, ResolveError, ValueError, TypeError) as exc:
                return _fail(exc)
            return _json(result)

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "ynab-mcp-lite",
                "version": __version__,
                "build": os.environ.get("YNAB_BUILD_COMMIT") or None,
            }
        )

    return server
