import tempfile
import unittest
from pathlib import Path

from ibkr_paper.broker import (
    InsufficientCash,
    InsufficientShares,
    PaperBroker,
    PaperError,
    UnknownSymbol,
)


class PaperBrokerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "paper.sqlite"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_buy_then_sell_round_trip(self) -> None:
        with PaperBroker(self.db, "1000.00", {"AAPL": "150.00"}) as broker:
            fill = broker.submit_market("buy", "aapl", 2)
            self.assertEqual(fill.status, "filled")
            self.assertEqual(fill.price, fill.price.__class__("150.00"))
            account = broker.account()
            self.assertEqual(account["cash"], "700.00")
            self.assertEqual(account["positions"], [
                {"symbol": "AAPL", "quantity": 2, "avg_price": "150.00"},
            ])
            broker.submit_market("sell", "AAPL", 2)
            flat = broker.account()
            self.assertEqual(flat["cash"], "1000.00")
            self.assertEqual(flat["positions"], [])

    def test_average_price_blends_buys(self) -> None:
        with PaperBroker(self.db, "10000", {"AAPL": "100.00"}) as broker:
            broker.submit_market("buy", "AAPL", 1)
            broker._conn.execute(
                "UPDATE prices SET price = ? WHERE symbol = 'AAPL'",
                ("200.00",),
            )
            broker._conn.commit()
            broker.submit_market("buy", "AAPL", 1)
            account = broker.account()
            self.assertEqual(account["positions"][0]["avg_price"], "150.00")
            self.assertEqual(account["positions"][0]["quantity"], 2)
            self.assertEqual(account["cash"], "9700.00")

    def test_rejects_insufficient_cash_and_shares(self) -> None:
        with PaperBroker(self.db, "100", {"AAPL": "150.00"}) as broker:
            with self.assertRaises(InsufficientCash):
                broker.submit_market("buy", "AAPL", 1)
            self.assertEqual(broker.account()["cash"], "100.00")
            with self.assertRaises(InsufficientShares):
                broker.submit_market("sell", "AAPL", 1)

    def test_unknown_symbol(self) -> None:
        with PaperBroker(self.db, "1000", {"AAPL": "10"}) as broker:
            with self.assertRaises(UnknownSymbol):
                broker.quote("TSLA")

    def test_client_order_id_is_idempotent(self) -> None:
        with PaperBroker(self.db, "1000", {"AAPL": "10.00"}) as broker:
            first = broker.submit_market("buy", "AAPL", 1, client_order_id="cid-1")
            second = broker.submit_market("buy", "AAPL", 1, client_order_id="cid-1")
            self.assertEqual(first.order_id, second.order_id)
            self.assertEqual(broker.account()["cash"], "990.00")
            self.assertEqual(broker.account()["positions"][0]["quantity"], 1)
            with self.assertRaises(PaperError):
                broker.submit_market("buy", "AAPL", 2, client_order_id="cid-1")

    def test_state_persists_across_open(self) -> None:
        with PaperBroker(self.db, "1000", {"MSFT": "320.00"}) as broker:
            broker.submit_market("buy", "MSFT", 1)
        with PaperBroker(self.db, "1", {"MSFT": "1.00"}) as broker:
            account = broker.account()
            self.assertEqual(account["cash"], "680.00")
            self.assertEqual(broker.quote("MSFT"), broker.quote("MSFT").__class__("320.00"))


if __name__ == "__main__":
    unittest.main()
