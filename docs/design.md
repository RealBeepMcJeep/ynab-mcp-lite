# ynab-mcp-lite — design

A deliberately tiny, non-destructive MCP server for YNAB, on the official API.

Status: **implemented** (v0.1.0) — server + 45-test suite green; container
build, GHCR publish and Dockge deploy kit in this repo. Writes ship disabled;
they are enabled only after a supervised read-only trial. Nothing here has
touched a live YNAB account yet.

## Principles (the whole point)

1. **Non-destructive by construction, not configuration.** The code implements
   only GET requests + "create transaction(s)" POSTs. No update, no delete, no
   import trigger, no budget/category mutations — those call paths do not
   exist. A CI guard (test suite) fails the build if a destructive HTTP verb
   or the `/transactions/import` endpoint ever appears in the source.
2. **Everything added is UNAPPROVED.** The server never sends `approved=true`
   (the request payload is built with `approved: false`; there is no
   `approved` parameter). Nothing affects the budget until the user approves
   it in the app. Recovery from any mistake = delete the unapproved entry in
   the app. (No API deletes, ever.)
3. **dry_run defaults to TRUE** on every write tool. A write happens only
   when the caller explicitly passes `dry_run=false` after a preview.
4. **Duplicate pre-check** before any add (same account, same amount,
   ±YNAB_DEDUPE_DAYS); refuses with the conflicting transaction(s) unless
   explicitly overridden (`allow_duplicate=true`).
5. **Stateless.** No stored data, no cache, no journal; token from env, never
   logged, never returned by any tool.
6. **Thin + auditable.** Official API only (api.ynab.com); two runtime
   dependencies (`mcp`, `httpx`); eight tools, all in one repository.

## Stack & deployment

- Python 3.12+, official `mcp` SDK v2 (`MCPServer` — the renamed FastMCP —
  with built-in streamable-HTTP transport), `httpx`. No other runtime deps.
- Docker: `python:3.12-slim`, non-root, no published ports
  (`hermes_internal` only), `/healthz` + `/mcp`, Docker healthcheck.
- Delivery mirrors the sibling MCP servers: GitHub repo → GitHub Actions
  (tests + GHCR publish) → Dockge stack → rollback by pinning
  `:sha-<commit>`.
- Module layout: `config.py` (env settings), `ynab.py` (client + helpers),
  `server.py` (tool surface), `__main__.py` (CLI: `serve`, HTTP or stdio).

## Tools (v1)

Reads (always available):

- `auth_status` — token validity + plan list + server config (no secrets)
- `list_plans`
- `list_accounts` (plan; optional include_closed) — id, name, type, on-budget, balance
- `list_categories` (plan; optional search / include_hidden)
- `list_payees` (plan; optional name search)
- `get_transactions` (plan; optional account, since_date, until_date,
  unapproved_only, limit)

Writes (only when `YNAB_ALLOW_WRITES=1`):

- `create_transaction` — account (name or id), date, amount, payee (name or
  id), optional category/memo/flag_color; `dry_run` default true;
  `allow_duplicate` overrides the pre-check.
- `create_transactions` — bulk (≤50), same rules; all items validated first —
  if anything fails, nothing is created.

Names resolve loosely (exact id → exact name → unique substring); ambiguity
is an error listing candidates, never a guess. The response echoes the
matched names/ids so a wrong resolution is visible. Payee names that don't
exist yet are passed through as `payee_name` (YNAB matches or creates them).
Amounts are dollars in, exact-decimal milliunits out.

Deliberately ABSENT: update, delete, approve/unapprove, import trigger,
category or budget moves, scheduled-transaction writes, account/payee
mutations, any "reconcile balance adjustment".

## Env

- `YNAB_API_TOKEN` (required; env only)
- `YNAB_ALLOW_WRITES` (default 0 = read-only deploy)
- `YNAB_PLAN_ID` (optional default plan; single plan auto-resolves)
- `YNAB_DEDUPE_DAYS` (default 10)
- `YNAB_ALLOWED_HOSTS` (Host allowlist for the HTTP transport; defaults cover
  the container name + localhost)
- `YNAB_BASE_URL` (default: official API; development only)
- `YNAB_MCP_HOST` / `YNAB_MCP_PORT` (bind address; default 127.0.0.1:8000)

## Workflow (screenshots → reconcile)

1. User sends a photo (receipt / statement page / card feed screenshot).
2. Hermes reads it (vision) and extracts candidate line items. (Not the
   server's job.)
3. Hermes pulls the account's recent transactions via `get_transactions`.
4. Matching: date ± days, exact amount, payee heuristics → "already there"
   vs "missing".
5. Preview shown to the user ("3 present, 2 missing — here they are"); user
   approves.
6. `create_transaction(s)` with `dry_run=false` → all added UNAPPROVED,
   optionally flagged (color/memo) for easy review.
7. Read-back verify; user approves (or deletes) in the app at leisure.

## Phases

0. ~~Build + unit tests against a fake YNAB.~~ **Done** — 45 tests, no network.
1. Read-only live trial (writes off): real token, pull accounts/transactions.
2. Enable writes: dry-run demo → one supervised small add → read-back → trust.
3. Daily use; write tools stay dry-run-default + unapproved-adds forever.

## Non-goals

Multi-tenant / OAuth / hosted service; ANY mutation beyond adding unapproved
transactions; auto-approval; balance reconciliation adjustments; storing user
data.

## Verification log

- Official `mcp` SDK **2.2.0** + `httpx` 0.28.1 on Python 3.12; server runs on
  the SDK's built-in streamable-HTTP transport (no bridge needed).
- SDK v2 note: FastMCP was renamed — `from mcp.server.mcpserver import MCPServer`.
- `custom_route` serves `/healthz` (verified live, HTTP 200).
- MCP handshake (initialize → list tools → call tool) verified live over real
  HTTP.
- DNS-rebinding protection is ON by default in the SDK transport: the Host
  header must match an allowlist entry exactly (with `:*` for any port) —
  hence `YNAB_ALLOWED_HOSTS`, defaulting to the container name + localhost.
- Test suite: 45 passing, including the destructive-call CI guard and the
  "created transactions are forced unapproved/cleared" assertions.
- Container: `python:3.12-slim`, non-root user, healthcheck against `/healthz`.

## Resolved decisions

- Repo name: `ynab-mcp-lite` (owner-confirmed).
- Public from day one (owner-confirmed).
- Write enablement is opt-in via `YNAB_ALLOW_WRITES=1` after the read-only
  trial; no auto-approval path exists.
- Flag/memo convention: optional per-call `flag_color` / `memo` — no forced
  convention; a workflow can adopt one (e.g. blue flag = added from statement).
- Default plan: single plan auto-resolves; multi-plan accounts set
  `YNAB_PLAN_ID` or pass `plan` per call.
