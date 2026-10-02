import unittest

from ibkr_paper.config import LiveTradingDisabled, load_settings


class LoadSettingsTest(unittest.TestCase):
    def test_defaults_to_paper(self) -> None:
        settings = load_settings({})
        self.assertEqual(settings.mode, "paper")
        self.assertEqual(str(settings.starting_cash), "100000")
        self.assertEqual(str(settings.db_path), ".paper/state.sqlite")

    def test_live_mode_is_refused(self) -> None:
        with self.assertRaises(LiveTradingDisabled):
            load_settings({"IBKR_TRADING_MODE": "live"})

    def test_blank_mode_is_refused(self) -> None:
        with self.assertRaises(LiveTradingDisabled):
            load_settings({"IBKR_TRADING_MODE": " "})

    def test_cash_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"IBKR_PAPER_CASH": "0"})


if __name__ == "__main__":
    unittest.main()
