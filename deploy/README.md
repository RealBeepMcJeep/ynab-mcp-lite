# ynab-mcp-lite — deployment kit (Komodo)

Portable **fail-closed template**, not a verified or deployed network configuration. **Internal-only: no ports published.** Admin must inspect current NAS MCPHub/backend Compose plus Docker network membership/aliases and verify that an existing private network joins MCPHub to `ynab-mcp-lite` before deployment. Set required `MCP_NETWORK` to that exact external name; `mcp_internal` is only a logical Compose key, not a claimed live network. Missing/empty `MCP_NETWORK` fails interpolation; never create a guessed network or publish port 8000 as a shortcut.

Hermes on ms-s1 reaches authenticated MCPHub at `http://truenas.ipfx.io:18090/mcp/hermes`. Only NAS MCPHub/the verified backend network uses `http://ynab-mcp-lite:8000/mcp`; the backend alias is not an ms-s1 URL.

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

## Offline template check

Run `python3 scripts/check_deploy_template.py` from the repository root. This
stdlib regression check checks the required-variable declaration and no-port
contract; it is **not** a Compose renderer or live network verification.
Before deployment, admin must use the real Docker Compose renderer with synthetic
credentials in a private scratch directory: missing and empty `MCP_NETWORK` must
fail; a dummy non-live network value must render successfully. Then verify the
actual NAS network membership separately. Do not deploy the dummy value.

## First deploy

1. Admin verifies the target NAS Docker engine and network membership above.
2. Review `compose.yaml` in the admin-managed Komodo stack or manual Compose workflow; preserve unrelated services.
3. Add required values to protected stack environment configuration or `.env`:

   ```
   MCP_NETWORK=<admin-verified existing private NAS network>
   YNAB_API_TOKEN=<YNAB Personal Access Token>
   ```

   (Leave `YNAB_ALLOW_WRITES` unset for the read-only first deploy.)
4. Admin validates with `docker compose --env-file <protected-stack-env> -f <compose-file> config --quiet` on the NAS (do not print rendered secrets), verifies no published ports and unchanged token/write/default-plan/dedupe settings, then explicitly pulls/recreates only this service via Komodo or manual Compose.
5. Read back the running image and network membership. Check health and the MCP handshake **from NAS MCPHub/the verified backend network**, not from Hermes on ms-s1:

   ```
   curl -fsS http://ynab-mcp-lite:8000/healthz
   python scripts/smoke.py http://ynab-mcp-lite:8000
   ```

   Then verify Hermes separately through authenticated MCPHub. Health/handshake alone does not prove account authorization or the running image revision. No live-account state is asserted by this template.

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

- **Update:** after CI/image verification, admin explicitly pulls the reviewed image and recreates only this service through Komodo or manual Compose. Do not infer pull/recreate semantics from a UI button; read back image and network membership.
- **Rollback:** pin the image to a known-good `:sha-<commit>` and redeploy.
- **Emergency local build** (CI down): admin first verifies a current source checkout and build context on the actual NAS Docker host, builds there and explicitly selects the local image. Hermes runs on ms-s1; no former NAS Hermes checkout is assumed.

## Notes / decisions

- **Token hygiene:** the YNAB token comes from the stack `.env` only; it is
  never logged, never returned by a tool, and never baked into the image.
- **Host allowlist:** the MCP transport matches Host headers exactly (no port
  stripping) — `ynab-mcp-lite:*` covers any port; see `YNAB_ALLOWED_HOSTS`.
- **No auth token on the MCP endpoint** (single-user, internal-only).
  Reachability is the boundary; add auth before any LAN exposure.
- Same house defaults as the sibling servers: `pull_policy: always`,
  `no-new-privileges`, memory cap, log rotation, rollback by pinned tag.
