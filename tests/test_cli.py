import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ibkr_paper.cli import main


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "paper.sqlite")
        self._env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _use_paper_env(self) -> None:
        os.environ["IBKR_TRADING_MODE"] = "paper"
        os.environ["IBKR_PAPER_CASH"] = "1000"
        os.environ["IBKR_PAPER_DB"] = self.db

    def test_buy_prints_fill_and_account(self) -> None:
        self._use_paper_env()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["buy", "AAPL", "1"])
        self.assertEqual(code, 0)
        self.assertIn("filled buy 1 AAPL @ 150.00", stdout.getvalue())
        self.assertIn("cash: 850.00", stdout.getvalue())

    def test_live_mode_exits_2(self) -> None:
        os.environ["IBKR_TRADING_MODE"] = "live"
        os.environ["IBKR_PAPER_DB"] = self.db
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["account"])
        self.assertEqual(code, 2)
        self.assertIn("paper mode only", stderr.getvalue())
        self.assertFalse(Path(self.db).exists())

    def test_module_round_trip(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        env["IBKR_TRADING_MODE"] = "paper"
        env["IBKR_PAPER_CASH"] = "1000"
        env["IBKR_PAPER_DB"] = self.db
        root = Path(__file__).resolve().parents[1]
        buy = subprocess.run(
            [sys.executable, "-m", "ibkr_paper", "--json", "buy", "SPY", "1"],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(buy.returncode, 0, buy.stderr)
        self.assertIn('"status": "filled"', buy.stdout)
        account = subprocess.run(
            [sys.executable, "-m", "ibkr_paper", "account"],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(account.returncode, 0, account.stderr)
        self.assertIn("cash: 500.00", account.stdout)
        self.assertIn("SPY 1 @ 500.00", account.stdout)


if __name__ == "__main__":
    unittest.main()
