# ynab-mcp-lite — deployment kit (Dockge)

Single-account **YNAB MCP server** — sibling of `donsetch` / `loseit-mcp` on
the `hermes_internal` network. **Internal-only: no ports published**; reach it
at `http://ynab-mcp-lite:8000/mcp`.

Read-first: **writes are OFF by default** (`YNAB_ALLOW_WRITES=0`). The first
deployment is read-only; enable the add-only write tools later by setting the
flag (see below).

The image is built by GitHub Actions (`.github/workflows/publish.yml`) and
published to GHCR as `ghcr.io/realbeepmcjeep/ynab-mcp-lite`. Every push to
`main` produces:

- `:sha-<commit>` — immutable, for rollbacks
- `:latest` — rolling, what the stack runs

The workflow smoke-tests the pushed image (starts it, `/healthz` + MCP
handshake) before finishing green.

## First deploy

1. In Dockge: **New Stack** → name it `ynab-mcp-lite` (or add the service to
   an existing stack, e.g. `mcp-servers`).
2. Paste `compose.yaml` (this directory) into the compose editor.
3. Add the stack **`.env`** (Dockge: "add .env" / files panel) with:

   ```
   YNAB_API_TOKEN=<YNAB Personal Access Token>
   ```

   (Leave `YNAB_ALLOW_WRITES` unset for the read-only first deploy.)
4. **Deploy.** The image pulls from GHCR (no local build needed).
5. **Verify:** Docker health turns green (~30 s), then from the Hermes
   container:

   ```
   curl -fsS http://ynab-mcp-lite:8000/healthz
   python scripts/smoke.py http://ynab-mcp-lite:8000
   ```

> If the pull fails with a permission error, the GHCR package is still
> private: make it public (package settings → Change visibility) or
> `docker login ghcr.io` on the NAS.

## Enable writes (after the read-only trial)

Add to the stack `.env`:

```
YNAB_ALLOW_WRITES=1
```

then **Deploy** again. The two add-only tools appear; every write is dry-run
by default and everything created is unapproved until approved in the YNAB app.

## Updating / rollback

- **Update:** push to `main` → CI publishes → **Update** in Dockge (pulls `:latest`).
- **Rollback:** pin the image to a known-good `:sha-<commit>` and redeploy.
- **Emergency local build** (CI down): on the NAS shell —
  `docker build -t ynab-mcp-lite:local /mnt/tank3/apps/hermes/projects/ynab-mcp-lite`
  — then point the stack at `ynab-mcp-lite:local`.

## Notes / decisions

- **Token hygiene:** the YNAB token comes from the stack `.env` only; it is
  never logged, never returned by a tool, and never baked into the image.
- **Host allowlist:** the MCP transport matches Host headers exactly (no port
  stripping) — `ynab-mcp-lite:*` covers any port; see `YNAB_ALLOWED_HOSTS`.
- **No auth token on the MCP endpoint** (single-user, internal-only).
  Reachability is the boundary; add auth before any LAN exposure.
- Same house defaults as the sibling servers: `pull_policy: always`,
  `no-new-privileges`, memory cap, log rotation, rollback by pinned tag.
