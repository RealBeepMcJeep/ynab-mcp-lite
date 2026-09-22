"""CLI entry point: ``ynab-mcp-lite serve`` (streamable HTTP) or stdio mode."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from . import __version__
from .config import Settings
from .server import build_transport_security, create_server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ynab-mcp-lite",
        description="Deliberately tiny, non-destructive MCP server for YNAB.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument(
        "--transport", choices=["streamable-http", "stdio"], default="streamable-http"
    )
    serve.add_argument("--host", default=os.environ.get("YNAB_MCP_HOST", "127.0.0.1"))
    serve.add_argument(
        "--port", type=int, default=int(os.environ.get("YNAB_MCP_PORT", "8000"))
    )

    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        transport = getattr(args, "transport", "streamable-http")
        settings = Settings.from_env()
        server = create_server(settings)
        if transport == "stdio":
            server.run(transport="stdio")
        else:
            host = getattr(args, "host", os.environ.get("YNAB_MCP_HOST", "127.0.0.1"))
            port = getattr(args, "port", int(os.environ.get("YNAB_MCP_PORT", "8000")))
            server.run(
                transport="streamable-http",
                host=host,
                port=port,
                transport_security=build_transport_security(settings),
            )
    else:  # pragma: no cover - argparse rejects anything else
        parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
