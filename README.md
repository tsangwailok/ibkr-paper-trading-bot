# ibkr-paper-trading-bot

Phase 1 is a local paper ledger. It fills market orders against seeded prices and stores cash, positions, and fills in SQLite. It does not connect to Interactive Brokers and it refuses any mode other than `paper`.

## Run

```bash
export PYTHONPATH=src
export IBKR_PAPER_DB=.paper/state.sqlite
python -m ibkr_paper account
python -m ibkr_paper quote AAPL
python -m ibkr_paper buy AAPL 10
python -m ibkr_paper sell AAPL 10
```

Seeded prices are AAPL 150.00, MSFT 320.00, and SPY 500.00. The default paper cash balance is 100000.00. Set `IBKR_PAPER_CASH` before the database is created to change it.

`IBKR_TRADING_MODE` defaults to `paper`. Any other value exits with status 2 and does not open the ledger.

Repeat a fill by passing the same `--client-order-id`. The second call returns the original fill and does not change cash or positions.

## Test

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
