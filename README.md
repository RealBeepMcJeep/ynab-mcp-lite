# ynab-mcp-lite

A deliberately tiny, **non-destructive** [MCP](https://modelcontextprotocol.io/)
server for [YNAB](https://www.ynab.com/), built on the official public API.
Read-first: the only write it can ever perform is *adding* transactions —
always **unapproved**, so nothing affects a budget until the account owner
reviews and approves it in the YNAB app.

## Why another YNAB MCP server?

Several exist. Most are stdio-first, and their safety is *configuration* — one
env flag away from full read-write against a budget. This one makes the
dangerous operations **impossible by construction**:

- Only `GET` requests and "create transaction(s)" `POST`s exist in the
  codebase. There is no code path for update, delete, approve,
  import-trigger, or any budget/category mutation — and a CI guard (part of
  the test suite) **fails the build** if a destructive call ever appears in
  the source.
- Created transactions are forced **unapproved**; the server cannot approve
  anything. Worst-case recovery for a wrong entry is deleting an unapproved
  item with two taps in the app.
- Every write tool is **dry-run by default** — preview first, explicit
  `dry_run=false` after that.
- A **duplicate pre-check** refuses to add an amount that already exists in
  the same account within ±N days, unless explicitly overridden.
- **Stateless.** No storage, no cache. The token comes from the environment
  and is never logged or returned by any tool.

## Tools

**Reads (always available)**

| tool | description |
|---|---|
| `auth_status` | token validity, plan list, server config |
| `list_plans` | plans (budgets) on the account |
| `list_accounts` | accounts: id, name, type, on-budget, balance |
| `list_categories` | categories + groups, budgeted/activity/balance |
| `list_payees` | payees, optional name search |
| `get_transactions` | transactions, filter by account / dates / unapproved |

**Add-only writes (registered only when `YNAB_ALLOW_WRITES=1`)**

| tool | description |
|---|---|
| `create_transaction` | add one transaction (dry-run default) |
| `create_transactions` | add up to 50 in one call |

Names (`account`, `payee`, `category`) resolve loosely: exact id, exact name,
or a unique substring — ambiguity is an error listing the candidates, never a
guess. Amounts are in dollars (e.g. `-12.34`) and converted to YNAB
milliunits with exact decimal math. Payee names that don't exist yet are
passed through so YNAB can create them.

## Status

- Server + 45-test suite green (no network: a fake YNAB over `httpx.MockTransport`)
- Container build, GHCR publish and Dockge deploy kit included (`deploy/`)
- Writes ship **disabled**; enable with `YNAB_ALLOW_WRITES=1` on a single-user deploy

## Quick start

### Docker

```bash
docker run --rm -p 8000:8000 \
  -e YNAB_API_TOKEN="<your token>" \
  ghcr.io/realbeepmcjeep/ynab-mcp-lite:latest
```

MCP endpoint: `http://localhost:8000/mcp` · health: `/healthz`.

### From source

```bash
uv sync
YNAB_API_TOKEN=<token> uv run ynab-mcp-lite serve                  # HTTP (127.0.0.1:8000)
YNAB_API_TOKEN=<token> uv run ynab-mcp-lite serve --transport stdio
```

### Use with an MCP client

HTTP clients: point at `http://<host>:8000/mcp`. For stdio clients:

```json
{
  "mcpServers": {
    "ynab": {
      "command": "ynab-mcp-lite",
      "args": ["serve", "--transport", "stdio"],
      "env": { "YNAB_API_TOKEN": "<your token>" }
    }
  }
}
```

## Configuration

All via environment; every variable except the token is optional.

| variable | default | meaning |
|---|---|---|
| `YNAB_API_TOKEN` | — | YNAB Personal Access Token (Settings → Developer) |
| `YNAB_ALLOW_WRITES` | `0` | `1` = register the add-only write tools |
| `YNAB_PLAN_ID` | — | default plan id; a single plan resolves automatically |
| `YNAB_DEDUPE_DAYS` | `10` | duplicate pre-check window, in days |
| `YNAB_ALLOWED_HOSTS` | container name + localhost | Host allowlist for the HTTP transport |
| `YNAB_BASE_URL` | `https://api.ynab.com/v1` | API base (development only) |
| `YNAB_MCP_HOST` / `YNAB_MCP_PORT` | `127.0.0.1` / `8000` | bind address for `serve` |

## Reconciliation workflow

The reason the write path exists: reconciling a card or account against a
statement / receipt screenshots.

1. Pull what's already recorded: `get_transactions` for the account and date
   range.
2. Diff against the statement (anywhere: chat, script, human).
3. Preview the additions with `create_transaction(s)` (dry-run default).
4. Create them for real (`dry_run=false`) — all **unapproved**, optionally
   flagged for easy review.
5. Approve them in the YNAB app when satisfied; the duplicate pre-check makes
   overlapping or re-sent statements safe to process.

## Development

```bash
uv sync
uv run ruff check src tests
uv run pytest          # offline — fake YNAB over httpx.MockTransport
uv run python scripts/smoke.py http://127.0.0.1:8000   # against a running server
```

## Deployment

`deploy/` contains a ready-made Dockge/compose stack: internal-only network,
no published ports, GHCR image with `pull_policy: always`, secrets via the
stack `.env`, rollback by pinning a `:sha-<commit>` tag.

## Design

See [docs/design.md](docs/design.md) for the full design and rationale.

## License

MIT — see [LICENSE](LICENSE).
