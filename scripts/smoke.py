#!/usr/bin/env python3
"""Protocol-level smoke test for a running ynab-mcp-lite server.

Usage:  python scripts/smoke.py [http://127.0.0.1:8000]

Checks /healthz, then connects over streamable HTTP, initializes a session,
lists tools (asserting the six read tools are present), and calls
auth_status. Read-only; exits non-zero on failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

READ_TOOLS = [
    "auth_status",
    "list_plans",
    "list_accounts",
    "list_categories",
    "list_payees",
    "get_transactions",
]
WRITE_TOOLS = ["create_transaction", "create_transactions"]


async def check_mcp(base_url: str) -> None:
    url = base_url.rstrip("/") + "/mcp"
    async with streamable_http_client(url) as streams:
        read, write = streams
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", names)
            missing = [n for n in READ_TOOLS if n not in names]
            assert not missing, f"missing read tools: {missing}"
            present_writes = [w for w in WRITE_TOOLS if w in names]
            if present_writes:
                print(f"note: write tools present (writes enabled): {present_writes}")
            else:
                print("reads-only server (writes disabled) — as expected by default")
            result = await session.call_tool("auth_status", {})
            block = result.content[0] if result.content else None
            text = getattr(block, "text", "") or ""
            parsed = json.loads(text)
            summary = {k: parsed.get(k) for k in ("ok", "error", "allow_writes", "dedupe_days")}
            print("auth_status:", json.dumps(summary, indent=2))
            print("MCP handshake: OK")


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    with urllib.request.urlopen(base.rstrip("/") + "/healthz", timeout=10) as resp:
        body = resp.read().decode()
        assert resp.status == 200, f"healthz status {resp.status}"
        print("healthz:", body)
    asyncio.run(check_mcp(base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
