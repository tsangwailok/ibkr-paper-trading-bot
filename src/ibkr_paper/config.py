"""Paper-only settings for the Phase 1 scaffold."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


class LiveTradingDisabled(RuntimeError):
    """Raised when a session asks for anything other than paper mode."""


@dataclass(frozen=True)
class Settings:
    mode: str
    starting_cash: Decimal
    db_path: Path


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Load settings. Phase 1 accepts paper mode only."""
    env = os.environ if environ is None else environ
    mode = env.get("IBKR_TRADING_MODE", "paper").strip().lower()
    if mode != "paper":
        raise LiveTradingDisabled(
            "Phase 1 supports paper mode only. "
            f"Refusing IBKR_TRADING_MODE={mode!r}."
        )

    raw_cash = env.get("IBKR_PAPER_CASH", "100000")
    try:
        starting_cash = Decimal(raw_cash)
    except InvalidOperation as exc:
        raise ValueError(f"IBKR_PAPER_CASH must be a number, got {raw_cash!r}.") from exc
    if starting_cash <= 0:
        raise ValueError("IBKR_PAPER_CASH must be positive.")

    db_path = Path(env.get("IBKR_PAPER_DB", ".paper/state.sqlite"))
    return Settings(mode="paper", starting_cash=starting_cash, db_path=db_path)
