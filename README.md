# ynab-mcp-lite

A deliberately tiny, **non-destructive** MCP server for YNAB (youneedabudget.com).
Read-only by default; the only write it can ever perform is *adding* transactions —
unapproved, so nothing affects the budget until the account owner approves it in the
YNAB app.

## Safety model (the whole point)

- The code implements **only GET requests and "create transaction" POSTs**. No update,
  no delete, no import trigger, no budget/category mutations — those call paths do not
  exist. A CI guard fails the build if a destructive HTTP verb ever appears.
- Created transactions are **forced unapproved** (no `approved` parameter exists).
- Every write tool defaults to **dry_run=true**; a write happens only with an explicit
  `dry_run=false` after a preview.
- **Duplicate pre-check** before any add (same account + amount +/- N days).
- **Stateless**: no stored data, no cache; the token comes from the environment, is
  never logged and never returned by any tool.

## Status

- [x] Design draft — see [docs/design.md](docs/design.md)
- [ ] Implementation + tests (against a fake YNAB)
- [ ] Read-only live trial (needs a YNAB Personal Access Token)
- [ ] Container + GHCR publish + Dockge stack
- [ ] Writes enabled

## Layout

    src/ynab_mcp_lite/   server code (Python, official `mcp` SDK)
    tests/               unit tests against a fake YNAB (no network)
    docs/design.md       full design document

## Development

    uv venv && uv pip install -e '.[dev]'   # or: pip install -e '.[dev]'
    pytest

## Deployment (planned)

Mirrors the sibling MCP servers: GitHub Actions build -> GHCR ->
Dockge stack on `hermes_internal` (no published ports, env-var secrets,
healthcheck, rollback by pinned image tag).
