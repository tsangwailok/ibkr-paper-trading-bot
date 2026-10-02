"""Local paper broker. Fills market orders against seeded prices."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SEED_PRICES: dict[str, str] = {
    "AAPL": "150.00",
    "MSFT": "320.00",
    "SPY": "500.00",
}

_CENT = Decimal("0.01")


class PaperError(ValueError):
    """Base class for rejected paper orders."""


class UnknownSymbol(PaperError):
    """Raised when a symbol has no paper price."""


class InsufficientCash(PaperError):
    """Raised when a buy costs more cash than the paper account holds."""


class InsufficientShares(PaperError):
    """Raised when a sell exceeds the paper position. Shorts are disabled."""


def money(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Fill:
    order_id: int
    client_order_id: str | None
    symbol: str
    side: str
    quantity: int
    price: Decimal
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": f"{self.price:.2f}",
            "status": self.status,
        }


class PaperBroker:
    """SQLite-backed paper account. Market orders fill immediately."""

    def __init__(
        self,
        db_path: Path | str,
        starting_cash: Decimal | str = "100000",
        prices: dict[str, str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init(money(starting_cash), prices or SEED_PRICES)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PaperBroker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def quote(self, symbol: str) -> Decimal:
        row = self._conn.execute(
            "SELECT price FROM prices WHERE symbol = ?",
            (self._symbol(symbol),),
        ).fetchone()
        if row is None:
            raise UnknownSymbol(f"No paper price for {self._symbol(symbol)}.")
        return money(row["price"])

    def account(self) -> dict[str, object]:
        cash = self._cash()
        positions = [
            {
                "symbol": row["symbol"],
                "quantity": row["quantity"],
                "avg_price": f"{money(row['avg_price']):.2f}",
            }
            for row in self._conn.execute(
                "SELECT symbol, quantity, avg_price FROM positions ORDER BY symbol"
            )
        ]
        return {"mode": "paper", "cash": f"{cash:.2f}", "positions": positions}

    def submit_market(
        self,
        side: str,
        symbol: str,
        quantity: int,
        client_order_id: str | None = None,
    ) -> Fill:
        normalized_side = side.strip().lower()
        if normalized_side not in {"buy", "sell"}:
            raise PaperError("side must be buy or sell.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise PaperError("quantity must be a positive integer.")
        ticker = self._symbol(symbol)
        client_id = client_order_id.strip() if client_order_id else None
        if client_order_id is not None and not client_id:
            raise PaperError("client_order_id cannot be blank.")

        if client_id:
            existing = self._order_by_client_id(client_id)
            if existing is not None:
                if (
                    existing.symbol != ticker
                    or existing.side != normalized_side
                    or existing.quantity != quantity
                ):
                    raise PaperError(
                        "client_order_id was already used for a different order."
                    )
                return existing

        price = self.quote(ticker)
        notional = money(price * quantity)

        with self._conn:
            if normalized_side == "buy":
                cash = self._cash()
                if cash < notional:
                    raise InsufficientCash(
                        f"Need {notional:.2f} to buy {quantity} {ticker}; cash is {cash:.2f}."
                    )
                self._set_cash(cash - notional)
                self._add_position(ticker, quantity, price)
            else:
                held = self._position_qty(ticker)
                if held < quantity:
                    raise InsufficientShares(
                        f"Cannot sell {quantity} {ticker}; paper position is {held}."
                    )
                self._set_cash(self._cash() + notional)
                self._reduce_position(ticker, quantity)

            cursor = self._conn.execute(
                """
                INSERT INTO orders (
                    client_order_id, symbol, side, quantity, price, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'filled', ?)
                """,
                (
                    client_id,
                    ticker,
                    normalized_side,
                    quantity,
                    f"{price:.2f}",
                    _now(),
                ),
            )
            order_id = int(cursor.lastrowid)

        return Fill(
            order_id=order_id,
            client_order_id=client_id,
            symbol=ticker,
            side=normalized_side,
            quantity=quantity,
            price=price,
            status="filled",
        )

    def _init(self, starting_cash: Decimal, prices: dict[str, str]) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prices (
                symbol TEXT PRIMARY KEY,
                price TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL,
                avg_price TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT UNIQUE,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'cash'").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('cash', ?)",
                (f"{starting_cash:.2f}",),
            )
        for symbol, price in prices.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO prices (symbol, price) VALUES (?, ?)",
                (self._symbol(symbol), f"{money(price):.2f}"),
            )
        self._conn.commit()

    def _cash(self) -> Decimal:
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'cash'").fetchone()
        if row is None:
            raise PaperError("Paper account is missing its cash balance.")
        return money(row["value"])

    def _set_cash(self, cash: Decimal) -> None:
        self._conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'cash'",
            (f"{money(cash):.2f}",),
        )

    def _position_qty(self, symbol: str) -> int:
        row = self._conn.execute(
            "SELECT quantity FROM positions WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return int(row["quantity"]) if row else 0

    def _add_position(self, symbol: str, quantity: int, price: Decimal) -> None:
        row = self._conn.execute(
            "SELECT quantity, avg_price FROM positions WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO positions (symbol, quantity, avg_price) VALUES (?, ?, ?)",
                (symbol, quantity, f"{price:.2f}"),
            )
            return
        old_qty = int(row["quantity"])
        old_avg = money(row["avg_price"])
        new_qty = old_qty + quantity
        new_avg = money((old_avg * old_qty + price * quantity) / new_qty)
        self._conn.execute(
            "UPDATE positions SET quantity = ?, avg_price = ? WHERE symbol = ?",
            (new_qty, f"{new_avg:.2f}", symbol),
        )

    def _reduce_position(self, symbol: str, quantity: int) -> None:
        held = self._position_qty(symbol)
        remaining = held - quantity
        if remaining == 0:
            self._conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            return
        self._conn.execute(
            "UPDATE positions SET quantity = ? WHERE symbol = ?",
            (remaining, symbol),
        )

    def _order_by_client_id(self, client_order_id: str) -> Fill | None:
        row = self._conn.execute(
            """
            SELECT id, client_order_id, symbol, side, quantity, price, status
            FROM orders WHERE client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        return Fill(
            order_id=int(row["id"]),
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=int(row["quantity"]),
            price=money(row["price"]),
            status=row["status"],
        )

    @staticmethod
    def _symbol(symbol: str) -> str:
        ticker = symbol.strip().upper()
        if not ticker or any(ch.isspace() for ch in ticker):
            raise PaperError("symbol must be a non-empty ticker.")
        return ticker


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
