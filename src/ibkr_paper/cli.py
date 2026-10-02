"""Command line for the Phase 1 paper ledger."""

from __future__ import annotations

import argparse
import json
import sys

from ibkr_paper.broker import PaperBroker, PaperError
from ibkr_paper.config import LiveTradingDisabled, load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibkr-paper",
        description="Phase 1 local paper ledger. Does not connect to a broker.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("account", help="Show paper cash and positions.")

    quote = sub.add_parser("quote", help="Show the seeded paper price.")
    quote.add_argument("symbol")

    for name in ("buy", "sell"):
        order = sub.add_parser(name, help=f"Fill a paper {name} market order.")
        order.add_argument("symbol")
        order.add_argument("quantity", type=int)
        order.add_argument("--client-order-id", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        with PaperBroker(settings.db_path, settings.starting_cash) as broker:
            payload = _run(broker, args)
    except LiveTradingDisabled as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (PaperError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_text(args.command, payload)
    return 0


def _run(broker: PaperBroker, args: argparse.Namespace) -> dict[str, object]:
    if args.command == "account":
        return broker.account()
    if args.command == "quote":
        price = broker.quote(args.symbol)
        return {"symbol": args.symbol.strip().upper(), "price": f"{price:.2f}"}
    fill = broker.submit_market(
        args.command,
        args.symbol,
        args.quantity,
        args.client_order_id,
    )
    account = broker.account()
    return {"fill": fill.as_dict(), "account": account}


def _print_text(command: str, payload: dict[str, object]) -> None:
    if command == "account":
        _print_account(payload)
        return
    if command == "quote":
        print(f"{payload['symbol']} {payload['price']}")
        return
    fill = payload["fill"]
    assert isinstance(fill, dict)
    print(
        f"filled {fill['side']} {fill['quantity']} {fill['symbol']} @ {fill['price']}"
    )
    account = payload["account"]
    assert isinstance(account, dict)
    _print_account(account)


def _print_account(account: dict[str, object]) -> None:
    print(f"mode: {account['mode']}")
    print(f"cash: {account['cash']}")
    positions = account["positions"]
    assert isinstance(positions, list)
    if not positions:
        print("positions: (none)")
        return
    print("positions:")
    for position in positions:
        assert isinstance(position, dict)
        print(
            f"  {position['symbol']} {position['quantity']} @ {position['avg_price']}"
        )
