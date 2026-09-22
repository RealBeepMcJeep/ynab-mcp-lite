"""Environment-driven configuration.

The YNAB token is read from the environment ONLY. Nothing in this package
writes it to disk, logs it, or returns it from a tool.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"", "0", "false", "no", "off"}

# Host allowlist for the HTTP transport (DNS-rebinding protection). The
# transport matches entries exactly, with "*" meaning "any port", so the
# container name must appear both bare and with ":*".
DEFAULT_ALLOWED_HOSTS = (
    "ynab-mcp-lite,ynab-mcp-lite:*,localhost,localhost:*,127.0.0.1,127.0.0.1:*,[::1],[::1]:*"
)

DEFAULT_BASE_URL = "https://api.ynab.com/v1"


@dataclass(frozen=True)
class Settings:
    token: str | None
    allow_writes: bool
    default_plan_id: str | None
    dedupe_days: int
    allowed_hosts: tuple[str, ...]
    base_url: str = DEFAULT_BASE_URL

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        token = (e.get("YNAB_API_TOKEN") or "").strip() or None

        raw_allow = (e.get("YNAB_ALLOW_WRITES") or "").strip().lower()
        if raw_allow in TRUTHY:
            allow_writes = True
        elif raw_allow in FALSY:
            allow_writes = False
        else:
            raise ValueError(
                "YNAB_ALLOW_WRITES must be one of: 1/true/yes/on or 0/false/no/off"
            )

        default_plan_id = (e.get("YNAB_PLAN_ID") or "").strip() or None

        raw_dedupe = (e.get("YNAB_DEDUPE_DAYS") or "10").strip()
        try:
            dedupe_days = int(raw_dedupe)
        except ValueError as exc:
            raise ValueError("YNAB_DEDUPE_DAYS must be an integer") from exc
        if dedupe_days < 0:
            raise ValueError("YNAB_DEDUPE_DAYS must be >= 0")

        hosts_raw = (e.get("YNAB_ALLOWED_HOSTS") or DEFAULT_ALLOWED_HOSTS).strip()
        allowed_hosts = tuple(h.strip() for h in hosts_raw.split(",") if h.strip())

        base_url = (e.get("YNAB_BASE_URL") or DEFAULT_BASE_URL).strip()

        return Settings(
            token=token,
            allow_writes=allow_writes,
            default_plan_id=default_plan_id,
            dedupe_days=dedupe_days,
            allowed_hosts=allowed_hosts,
            base_url=base_url,
        )
