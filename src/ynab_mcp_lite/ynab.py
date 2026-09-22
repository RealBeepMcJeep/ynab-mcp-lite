"""Thin client and helpers for the official YNAB API (api.ynab.com).

Intentional design limits — do not extend without a very good reason:

* Only ``GET`` is implemented, plus ``POST`` for the two transaction-create
  endpoints. There is no update, no delete, and no bank-import trigger
  anywhere in this package; the test suite fails if such a call ever appears.
* Amounts convert between dollars (what callers see) and YNAB's milliunits
  (integer, 1/1000 currency unit) with exact decimal math.
* Names resolve loosely (exact id, exact name, then unique substring);
  ambiguity is an error, never a guess.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Self

import httpx

__all__ = [
    "FLAG_COLORS",
    "ResolveError",
    "YnabClient",
    "YnabError",
    "amount_to_milliunits",
    "apply_names",
    "error_from_response",
    "find_amount_matches",
    "flatten_categories",
    "milliunits_to_amount",
    "parse_amount",
    "parse_date",
    "resolve_one",
    "trim_transaction",
]

_MONEY_RE = re.compile(r"^-?\d+(\.\d{1,3})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

#: Valid YNAB flag colors (empty/None means "no flag").
FLAG_COLORS = {"red", "orange", "yellow", "green", "blue", "purple"}


class YnabError(Exception):
    """A structured error from the YNAB API (or the request layer)."""

    def __init__(self, status: int | None, name: str, detail: str):
        super().__init__(detail or name)
        self.status = status
        self.name = name
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.name, "message": self.detail}
        if self.status is not None:
            out["status"] = self.status
        return out


class ResolveError(Exception):
    """A name/id reference did not resolve to exactly one entity."""

    def __init__(
        self,
        kind: str,
        ref: str,
        reason: str,
        *,
        failure: str = "not_found",
        candidates: Iterable[dict[str, Any]] = (),
    ):
        super().__init__(reason)
        self.kind = kind
        self.ref = ref
        self.reason = reason
        self.failure = failure  # "not_found" | "ambiguous" | "invalid_id" | "empty"
        self.candidates = list(candidates)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "error": f"{self.kind}_not_resolved",
            "failure": self.failure,
            "message": self.reason,
            "input": self.ref,
        }
        if self.candidates:
            out["candidates"] = self.candidates[:15]
        return out


class YnabClient:
    """Minimal request layer over the official API.

    Public surface is deliberately just ``get``, ``post``, and ``close``.
    The token lives only in the request headers; it is never logged and
    never returned.
    """

    def __init__(
        self,
        token: str | None,
        *,
        base_url: str = "https://api.ynab.com/v1",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=base_url, headers=headers, timeout=timeout, transport=transport
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise YnabError(
                None, "connection_error", f"could not reach YNAB ({exc.__class__.__name__})"
            ) from exc
        if response.status_code >= 400:
            raise error_from_response(response)
        try:
            return response.json()
        except ValueError as exc:
            raise YnabError(
                response.status_code, "invalid_response", "YNAB returned a non-JSON response"
            ) from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def error_from_response(response: httpx.Response) -> YnabError:
    name = f"http_{response.status_code}"
    detail = ""
    try:
        body = response.json()
        err = body.get("error") or {}
        name = str(err.get("name") or name)
        detail = str(err.get("detail") or "")
    except ValueError:
        detail = (response.text or "")[:200]
    if response.status_code == 429 and name in {"http_429", "too_many_requests"}:
        name = "rate_limited"
        detail = detail or "YNAB API rate limit reached (200 requests/hour); try again later."
    return YnabError(response.status_code, name, detail)


# --------------------------------------------------------------------------
# Amounts and dates
# --------------------------------------------------------------------------


def parse_amount(value: str | float | Decimal) -> Decimal:
    """Parse a dollar amount the caller supplied ("-12.34", 12.34, ...)."""
    if isinstance(value, bool):
        raise TypeError("amount must be a number, not a boolean")
    if isinstance(value, (Decimal, int)):
        text = str(value)
    elif isinstance(value, float):
        text = repr(value)
    else:
        text = str(value).strip()
    if not _MONEY_RE.match(text):
        raise ValueError(f"amount must look like -12.34 (up to 3 decimals), got: {text!r}")
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - the regex guards this
        raise ValueError(f"amount is not a valid number: {text!r}") from exc


def amount_to_milliunits(amount: Decimal) -> int:
    scaled = amount * 1000
    if scaled != scaled.to_integral_value():
        raise ValueError("amount has more than 3 decimal places")
    return int(scaled)


def milliunits_to_amount(milliunits: int) -> str:
    """Render milliunits as an exact dollar string, e.g. -7450 -> \"-7.45\"."""
    sign = "-" if milliunits < 0 else ""
    whole, frac = divmod(abs(int(milliunits)), 1000)
    frac_text = f"{frac:03d}".rstrip("0")
    return f"{sign}{whole}" + (f".{frac_text}" if frac_text else "")


def parse_date(value: str) -> date:
    text = str(value).strip()
    if not _DATE_RE.match(text):
        raise ValueError(f"date must be YYYY-MM-DD, got: {value!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid date: {value!r}") from exc


# --------------------------------------------------------------------------
# Name resolution
# --------------------------------------------------------------------------


def _norm(value: str) -> str:
    return " ".join(str(value).lower().split())


def _summarize(item: dict[str, Any], id_field: str, name_field: str) -> dict[str, Any]:
    return {"id": item.get(id_field), "name": item.get(name_field)}


def resolve_one(
    kind: str,
    items: Iterable[dict[str, Any]],
    ref: str,
    *,
    id_field: str = "id",
    name_field: str = "name",
) -> dict[str, Any]:
    """Resolve an id-or-name reference to exactly one non-deleted entity.

    Priority: exact id, exact (case-insensitive) name, unique substring.
    Raises :class:`ResolveError` when nothing or several things match.
    """
    ref = str(ref).strip()
    if not ref:
        raise ResolveError(kind, ref, f"empty {kind} reference", failure="empty")

    pool = [i for i in items if not i.get("deleted")]

    for item in pool:
        if item.get(id_field) == ref:
            return item

    if _UUID_RE.match(ref):
        raise ResolveError(
            kind, ref, f"no {kind} with id {ref} exists in this plan", failure="invalid_id"
        )

    nref = _norm(ref)
    exact = [i for i in pool if _norm(str(i.get(name_field) or "")) == nref]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ResolveError(
            kind,
            ref,
            f"{len(exact)} {kind}s are named {ref!r} — pass the id instead",
            failure="ambiguous",
            candidates=[_summarize(i, id_field, name_field) for i in exact],
        )

    subs = [i for i in pool if nref in _norm(str(i.get(name_field) or ""))]
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        raise ResolveError(
            kind,
            ref,
            f"{len(subs)} {kind}s match {ref!r} — pass a more specific name or the id",
            failure="ambiguous",
            candidates=[_summarize(i, id_field, name_field) for i in subs],
        )
    raise ResolveError(kind, ref, f"no {kind} matches {ref!r}", failure="not_found")


# --------------------------------------------------------------------------
# Plan details, categories, transactions
# --------------------------------------------------------------------------


def flatten_categories(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-deleted categories from a plan detail, each tagged with ``_group``.

    Handles both shapes the API has used: a flat ``categories`` list carrying
    ``category_group_id`` / ``category_group_name``, and ``category_groups``
    with nested ``categories``.
    """
    out: list[dict[str, Any]] = []

    group_names = {
        g.get("id"): g.get("name")
        for g in (plan.get("category_groups") or [])
        if not g.get("deleted")
    }

    for cat in plan.get("categories") or []:
        if cat.get("deleted"):
            continue
        tagged = dict(cat)
        tagged["_group"] = cat.get("category_group_name") or group_names.get(
            cat.get("category_group_id")
        )
        out.append(tagged)

    if not out:  # nested-only shape
        for group in plan.get("category_groups") or []:
            if group.get("deleted"):
                continue
            for cat in group.get("categories") or []:
                if cat.get("deleted"):
                    continue
                tagged = dict(cat)
                tagged["_group"] = group.get("name")
                out.append(tagged)

    return out


def find_amount_matches(
    transactions: Iterable[dict[str, Any]],
    amount_milliunits: int,
    tx_date: date,
    window_days: int,
) -> list[dict[str, Any]]:
    """Existing non-deleted transactions with this exact amount within ±window_days."""
    matches = []
    for tx in transactions:
        if tx.get("deleted") or tx.get("amount") != amount_milliunits:
            continue
        try:
            other = date.fromisoformat(str(tx.get("date")))
        except ValueError:
            continue
        if abs((other - tx_date).days) <= window_days:
            matches.append(tx)
    return matches


def apply_names(
    tx: dict[str, Any],
    accounts: dict[str, Any],
    payees: dict[str, Any],
    categories: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing *_name fields from id->name maps (list endpoints omit names)."""
    out = dict(tx)
    if not out.get("account_name"):
        out["account_name"] = accounts.get(str(out.get("account_id")))
    if not out.get("payee_name") and out.get("payee_id"):
        out["payee_name"] = payees.get(str(out.get("payee_id")))
    if not out.get("category_name") and out.get("category_id"):
        out["category_name"] = categories.get(str(out.get("category_id")))
    return out


def trim_transaction(tx: dict[str, Any]) -> dict[str, Any]:
    """Compact, stable view of a transaction for tool output."""
    amount_mu = int(tx.get("amount") or 0)
    return {
        "id": tx.get("id"),
        "date": tx.get("date"),
        "amount": milliunits_to_amount(amount_mu),
        "amount_milliunits": amount_mu,
        "account": tx.get("account_name") or tx.get("account_id"),
        "payee": tx.get("payee_name"),
        "payee_id": tx.get("payee_id"),
        "category": tx.get("category_name"),
        "category_id": tx.get("category_id"),
        "memo": tx.get("memo"),
        "approved": tx.get("approved"),
        "cleared": tx.get("cleared"),
        "flag": tx.get("flag_color") or None,
        "transfer_account_id": tx.get("transfer_account_id"),
    }
