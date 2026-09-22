# ynab-mcp-lite — design draft v0.1

A deliberately tiny, non-destructive MCP server for YNAB, on the official API.
Status: approved; build in progress (scaffold first). Nothing here touches the YNAB account.

## Principles (the whole point)
1. **Non-destructive by construction, not configuration.** The code implements only:
   GET requests + "create transaction(s)" POSTs. No update, no delete, no import
   trigger, no budget/category mutations — those call paths do not exist. A CI guard
   fails the build if a destructive HTTP verb or the /import endpoint ever appears.
2. **Everything added is UNAPPROVED.** YNAB's API default for created transactions is
   unapproved; the server never overrides it (no `approved` parameter exists).
   Nothing affects the budget until the user approves it in the app. Recovery from
   any mistake = delete the unapproved entry in the app. (No API deletes, ever.)
3. **dry_run defaults to TRUE** on every write tool. A write only happens when the
   caller explicitly passes dry_run=false after a preview.
4. **Duplicate pre-check** before any add (same account, same amount, +/- YNAB_DEDUPE_DAYS);
   refuses with the conflicting transaction(s) unless explicitly overridden.
5. **Stateless.** No stored data, no cache, no journal; token from env, never logged,
   never returned by any tool.
6. **Thin + auditable.** Official API only (api.ynab.com); pinned deps; ~10 tools.

## Stack & deployment
- Python 3.12+, official `mcp` SDK v2 (`MCPServer` — the renamed FastMCP — with built-in streamable-HTTP transport), `httpx`.
- Docker: python-slim, non-root, no published ports (hermes_internal only), /healthz + /mcp.
- Delivery mirrors the proven loseit pattern: GitHub repo -> GitHub Actions (tests + GHCR
  publish) -> Dockge stack sibling of donsetch/loseit-mcp -> rollback by pinning :sha-<commit>.

## Tools (v1)
Reads (always available):
- `auth_status` — token validity + basic plan list (no secrets)
- `list_plans`
- `list_accounts` (plan) — id, name, type, on-budget, balance
- `list_categories` (plan)
- `list_payees` (plan, optional name search)
- `get_transactions` (plan; optional account, since_date, until_date, only_unapproved, limit)

Writes (only when `YNAB_ALLOW_WRITES=1`):
- `create_transaction` — account (name or id), date, amount, payee (name or id),
  optional category/memo/flag_color; `dry_run` default true.
  Names resolve loosely (exact then fuzzy); ambiguity = error listing candidates;
  response echoes the matched names so a wrong guess is visible.
- `create_transactions` — bulk, same validation, for statement runs.

Deliberately ABSENT: update, delete, approve/unapprove, import trigger, category or
budget moved money, scheduled-transaction writes, account/payee mutations, any
"reconcile balance adjustment".

## Env
- `YNAB_API_TOKEN` (required; env only)
- `YNAB_ALLOW_WRITES` (default 0 = read-only deploy)
- `YNAB_PLAN_ID` (optional default plan)
- `YNAB_DEDUPE_DAYS` (default 10)

## Workflow (screenshots -> reconcile)
1. User sends a photo (receipt / statement page / card feed screenshot).
2. Hermes reads it (vision) and extracts candidate line items. (Not the server's job.)
3. Hermes pulls the account's recent transactions via `get_transactions`.
4. Matching: date +/- days, exact amount, payee heuristics -> "already there" vs "missing".
5. Preview shown to user ("3 present, 2 missing — here they are"); user approves.
6. `create_transaction(s)` with dry_run=false -> all added UNAPPROVED, optionally flagged
   (color/memo convention TBD) for easy review.
7. Read-back verify; user approves (or deletes) in the app at leisure.

## Phases
0. Build + unit tests against a fake YNAB (mocked transport). No token, no account access.
1. Read-only live trial (writes off): real token, pull accounts/transactions, validate.
2. Enable writes: dry-run demo -> one supervised small add -> read-back -> trust.
3. Daily use; write tools stay dry_run-default + unapproved-adds forever.

## Non-goals
Multi-tenant / OAuth / hosted service; ANY mutation beyond adding unapproved
transactions; auto-approval; balance reconciliation adjustments; storing user data.

## Sandbox verification (done)
- Official `mcp` SDK **2.2.0** + `httpx` 0.28.1 install cleanly on Python 3.12; no extra deps for a server.
- SDK v2 note: FastMCP was renamed; server class is `from mcp.server.mcpserver import MCPServer`.
- Streamable-HTTP transport is built into the SDK (`server/streamable_http.py`, `StreamableHTTPSessionManager`) — the container serves `/mcp` directly, no bridge needed.
- `MCPServer` import verified: True; tool decorator present: True.

## Open questions (for the human)
- Repo name: `ynab-mcp-lite` (working title) — alternatives welcome.
- Public from day one, or private until the MVP is green?
- Flag color / memo convention for "added by Hermes" items?
- Default plan selection (or always ask)?
