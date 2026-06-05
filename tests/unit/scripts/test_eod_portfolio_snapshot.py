"""Unit tests for scripts/eod_portfolio_snapshot.py.

The script lives in scripts/ (not an importable package), so we load it by path.
These tests exercise the pure parsing/formatting/writing logic with sample Schwab
get_account JSON payloads — no live Schwab calls.

Schema reflects kurama's A1 decision (QUESTIONS.md): multi-account snapshot —
positions carry an `account_id` first column; the account CSV is one row per
account.
"""
import csv
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "eod_portfolio_snapshot.py"

POSITIONS_HEADER = (
    "account_id,as_of_date,asset_type,symbol,quantity,average_price,market_value,"
    "underlying,option_type,strike,expiration,unrealized_pnl,day_pnl"
)
ACCOUNT_HEADER = (
    "account_id,as_of_date,total_equity,cash,buying_power,"
    "long_market_value,short_market_value"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("eod_portfolio_snapshot", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eod = _load_module()


# --------------------------------------------------------------------------- #
# Sample Schwab get_account JSON (securitiesAccount shape, POSITIONS fields)   #
# --------------------------------------------------------------------------- #
def _sample_account_json():
    return {
        "securitiesAccount": {
            "type": "MARGIN",
            "accountNumber": "12345678",
            "currentBalances": {
                "liquidationValue": 152340.55,
                "cashBalance": 10250.00,
                "buyingPower": 40000.00,
                "longMarketValue": 142090.55,
                "shortMarketValue": -1500.00,
            },
            "positions": [
                {
                    "instrument": {"assetType": "EQUITY", "symbol": "QQQ"},
                    "longQuantity": 100.0,
                    "shortQuantity": 0.0,
                    "averagePrice": 380.12,
                    "marketValue": 40000.00,
                    "longOpenProfitLoss": 1988.00,
                    "currentDayProfitLoss": 120.00,
                },
                {
                    "instrument": {"assetType": "EQUITY", "symbol": "PSQ"},
                    "longQuantity": 0.0,
                    "shortQuantity": 50.0,
                    "averagePrice": 11.20,
                    "marketValue": -1500.00,
                    "shortOpenProfitLoss": -940.00,
                },
                {
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": "QQQ   251219P00300000",
                        "putCall": "PUT",
                        "underlyingSymbol": "QQQ",
                    },
                    "longQuantity": 2.0,
                    "shortQuantity": 0.0,
                    "averagePrice": 5.30,
                    "marketValue": 980.00,
                    "longOpenProfitLoss": -60.00,
                },
            ],
        }
    }


def _second_account_json():
    return {
        "securitiesAccount": {
            "type": "CASH",
            "accountNumber": "87654321",
            "currentBalances": {
                "liquidationValue": 50000.00,
                "cashBalance": 5000.00,
                "buyingPower": 5000.00,
                "longMarketValue": 45000.00,
                "shortMarketValue": 0.0,
            },
            "positions": [
                {
                    "instrument": {"assetType": "EQUITY", "symbol": "TLT"},
                    "longQuantity": 500.0,
                    "shortQuantity": 0.0,
                    "averagePrice": 90.00,
                    "marketValue": 45000.00,
                    "longOpenProfitLoss": 250.00,
                },
            ],
        }
    }


# --------------------------------------------------------------------------- #
# parse_occ_symbol                                                             #
# --------------------------------------------------------------------------- #
def test_parse_occ_symbol_put_with_padding():
    result = eod.parse_occ_symbol("QQQ   251219P00300000")
    assert result == {
        "underlying": "QQQ",
        "option_type": "PUT",
        "strike": Decimal("300"),
        "expiration": "2025-12-19",
    }


def test_parse_occ_symbol_call_fractional_strike():
    result = eod.parse_occ_symbol("AAPL  240119C00150500")
    assert result["underlying"] == "AAPL"
    assert result["option_type"] == "CALL"
    assert result["strike"] == Decimal("150.5")
    assert result["expiration"] == "2024-01-19"


def test_parse_occ_symbol_returns_none_for_equity_ticker():
    assert eod.parse_occ_symbol("QQQ") is None


# --------------------------------------------------------------------------- #
# format_value                                                                #
# --------------------------------------------------------------------------- #
def test_format_value_none_is_empty_string():
    assert eod.format_value(None) == ""


def test_format_value_decimal_normalized():
    assert eod.format_value(Decimal("300")) == "300"
    assert eod.format_value(Decimal("150.5")) == "150.5"


# --------------------------------------------------------------------------- #
# position_to_row (carries account_id + day_pnl)                             #
# --------------------------------------------------------------------------- #
def test_position_to_row_equity_long():
    pos = _sample_account_json()["securitiesAccount"]["positions"][0]
    row = eod.position_to_row(pos, "2026-06-04", "ACCT1")
    assert row["account_id"] == "ACCT1"
    assert row["as_of_date"] == "2026-06-04"
    assert row["asset_type"] == "EQUITY"
    assert row["symbol"] == "QQQ"
    assert row["quantity"] == "100"
    assert row["average_price"] == "380.12"
    assert row["market_value"] == "40000.0"
    assert row["underlying"] == ""
    assert row["option_type"] == ""
    assert row["strike"] == ""
    assert row["expiration"] == ""
    assert row["unrealized_pnl"] == "1988.0"
    assert row["day_pnl"] == "120.0"


def test_position_to_row_short_equity_has_negative_quantity():
    pos = _sample_account_json()["securitiesAccount"]["positions"][1]
    row = eod.position_to_row(pos, "2026-06-04", "ACCT1")
    assert row["quantity"] == "-50"
    assert row["unrealized_pnl"] == "-940.0"
    assert row["day_pnl"] == ""  # currentDayProfitLoss absent -> blank


def test_position_to_row_option_fills_option_columns():
    pos = _sample_account_json()["securitiesAccount"]["positions"][2]
    row = eod.position_to_row(pos, "2026-06-04", "ACCT1")
    assert row["asset_type"] == "OPTION"
    assert row["symbol"] == "QQQ   251219P00300000"
    assert row["quantity"] == "2"
    assert row["underlying"] == "QQQ"
    assert row["option_type"] == "PUT"
    assert row["strike"] == "300"
    assert row["expiration"] == "2025-12-19"


# --------------------------------------------------------------------------- #
# extract_positions / extract_account_row (per account)                       #
# --------------------------------------------------------------------------- #
def test_extract_positions_returns_row_per_position_with_account_id():
    rows = eod.extract_positions(_sample_account_json(), "2026-06-04", "ACCT1")
    assert len(rows) == 3
    assert [r["symbol"] for r in rows] == ["QQQ", "PSQ", "QQQ   251219P00300000"]
    assert all(r["account_id"] == "ACCT1" for r in rows)


def test_extract_account_row_maps_balances():
    row = eod.extract_account_row(_sample_account_json(), "2026-06-04", "ACCT1")
    assert row["account_id"] == "ACCT1"
    assert row["as_of_date"] == "2026-06-04"
    assert row["total_equity"] == "152340.55"
    assert row["cash"] == "10250.0"
    assert row["buying_power"] == "40000.0"
    assert row["long_market_value"] == "142090.55"
    assert row["short_market_value"] == "-1500.0"


def test_extract_account_row_blanks_missing_balances():
    payload = {"securitiesAccount": {"currentBalances": {"liquidationValue": 100.0}}}
    row = eod.extract_account_row(payload, "2026-06-04", "ACCT1")
    assert row["total_equity"] == "100.0"
    assert row["cash"] == ""
    assert row["buying_power"] == ""
    assert row["long_market_value"] == ""
    assert row["short_market_value"] == ""


# --------------------------------------------------------------------------- #
# build_snapshot — aggregate across multiple accounts                         #
# --------------------------------------------------------------------------- #
def test_build_snapshot_aggregates_all_accounts():
    accounts = [
        ("ACCT1", _sample_account_json()),
        ("ACCT2", _second_account_json()),
    ]
    pos_rows, acct_rows = eod.build_snapshot(accounts, "2026-06-04")
    # positions: one row per position across BOTH accounts
    assert len(pos_rows) == 4
    assert {r["account_id"] for r in pos_rows} == {"ACCT1", "ACCT2"}
    assert [r["symbol"] for r in pos_rows][-1] == "TLT"
    # account: one row PER account
    assert len(acct_rows) == 2
    assert [r["account_id"] for r in acct_rows] == ["ACCT1", "ACCT2"]
    assert acct_rows[1]["total_equity"] == "50000.0"


# --------------------------------------------------------------------------- #
# write_snapshot — atomic latest + dated files, one-row-per-account           #
# --------------------------------------------------------------------------- #
def test_write_snapshot_creates_dated_and_latest_files(tmp_path):
    accounts = [("ACCT1", _sample_account_json()), ("ACCT2", _second_account_json())]
    pos_rows, acct_rows = eod.build_snapshot(accounts, "2026-06-04")

    eod.write_snapshot(tmp_path, "2026-06-04", pos_rows, acct_rows)

    for name in [
        "positions-2026-06-04.csv",
        "account-2026-06-04.csv",
        "latest.csv",
        "latest-account.csv",
    ]:
        assert (tmp_path / name).exists(), f"{name} not written"

    with open(tmp_path / "latest.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    assert rows[0]["account_id"] == "ACCT1"
    assert rows[0]["symbol"] == "QQQ"

    with open(tmp_path / "latest.csv", newline="") as f:
        assert f.readline().strip() == POSITIONS_HEADER

    with open(tmp_path / "latest-account.csv", newline="") as f:
        header = f.readline().strip()
        body = list(csv.DictReader(f, fieldnames=ACCOUNT_HEADER.split(",")))
    assert header == ACCOUNT_HEADER
    assert len(body) == 2  # one row per account


def test_write_snapshot_idempotent_overwrites_same_date(tmp_path):
    accounts = [("ACCT1", _sample_account_json())]
    pos_rows, acct_rows = eod.build_snapshot(accounts, "2026-06-04")
    eod.write_snapshot(tmp_path, "2026-06-04", pos_rows, acct_rows)
    eod.write_snapshot(tmp_path, "2026-06-04", pos_rows[:1], acct_rows)
    with open(tmp_path / "positions-2026-06-04.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_write_snapshot_does_not_touch_other_dates(tmp_path):
    accounts = [("ACCT1", _sample_account_json())]
    pos_rows, acct_rows = eod.build_snapshot(accounts, "2026-06-04")
    eod.write_snapshot(tmp_path, "2026-06-03", pos_rows, acct_rows)
    eod.write_snapshot(tmp_path, "2026-06-04", pos_rows[:1], acct_rows)
    with open(tmp_path / "positions-2026-06-03.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3


def test_build_snapshot_raises_on_missing_securities_account():
    with pytest.raises(KeyError):
        eod.build_snapshot([("ACCT1", {})], "2026-06-04")


# --------------------------------------------------------------------------- #
# main() orchestration — dry-run, success, failure-preserves-latest, skip     #
# --------------------------------------------------------------------------- #
def _patch_schwab(monkeypatch, accounts=None, fetch_error=None):
    monkeypatch.setattr(eod, "build_schwab_client", lambda: object())
    if fetch_error is not None:
        def _boom(_client):
            raise fetch_error
        monkeypatch.setattr(eod, "fetch_accounts", _boom)
    else:
        monkeypatch.setattr(eod, "fetch_accounts", lambda _client: accounts)


def test_main_success_writes_all_accounts(tmp_path, monkeypatch):
    accounts = [("ACCT1", _sample_account_json()), ("ACCT2", _second_account_json())]
    _patch_schwab(monkeypatch, accounts=accounts)
    rc = eod.main(
        ["--date", "2026-06-04", "--out", str(tmp_path), "--ignore-market-calendar"]
    )
    assert rc == 0
    with open(tmp_path / "latest.csv", newline="") as f:
        assert len(list(csv.DictReader(f))) == 4
    with open(tmp_path / "latest-account.csv", newline="") as f:
        assert len(list(csv.DictReader(f))) == 2


def test_main_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    accounts = [("ACCT1", _sample_account_json())]
    _patch_schwab(monkeypatch, accounts=accounts)
    rc = eod.main(["--date", "2026-06-04", "--out", str(tmp_path), "--dry-run"])
    assert rc == 0
    assert list(tmp_path.iterdir()) == []
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "QQQ" in out


def test_main_failure_preserves_existing_latest(tmp_path, monkeypatch):
    sentinel = tmp_path / "latest.csv"
    sentinel.write_text("prior good snapshot\n")
    sentinel_account = tmp_path / "latest-account.csv"
    sentinel_account.write_text("prior good account\n")

    _patch_schwab(monkeypatch, fetch_error=RuntimeError("schwab auth failed"))
    rc = eod.main(
        ["--date", "2026-06-04", "--out", str(tmp_path), "--ignore-market-calendar"]
    )
    assert rc == 1
    assert sentinel.read_text() == "prior good snapshot\n"
    assert sentinel_account.read_text() == "prior good account\n"


def test_main_skips_non_trading_day(tmp_path, monkeypatch):
    accounts = [("ACCT1", _sample_account_json())]
    _patch_schwab(monkeypatch, accounts=accounts)
    monkeypatch.setattr(eod, "_is_trading_day", lambda d: False)
    rc = eod.main(["--date", "2026-06-06", "--out", str(tmp_path)])
    assert rc == 0
    assert list(tmp_path.iterdir()) == []


def test_main_invalid_date_returns_error(tmp_path):
    rc = eod.main(["--date", "06/04/2026", "--out", str(tmp_path)])
    assert rc == 2


# --------------------------------------------------------------------------- #
# run_snapshot_to — importable entry point used by the Docker scheduler       #
# --------------------------------------------------------------------------- #
def test_run_snapshot_to_writes_and_returns_summary(tmp_path, monkeypatch):
    import datetime
    accounts = [("ACCT1", _sample_account_json()), ("ACCT2", _second_account_json())]
    monkeypatch.setattr(eod, "build_schwab_client", lambda: object())
    monkeypatch.setattr(eod, "fetch_accounts", lambda _c: accounts)

    summary = eod.run_snapshot_to(str(tmp_path), datetime.date(2026, 6, 4))

    assert summary == {"as_of_date": "2026-06-04", "accounts": 2, "positions": 4}
    assert (tmp_path / "latest.csv").exists()
    assert (tmp_path / "latest-account.csv").exists()


def test_run_snapshot_to_raises_and_writes_nothing_on_fetch_error(tmp_path, monkeypatch):
    import datetime
    monkeypatch.setattr(eod, "build_schwab_client", lambda: object())

    def _boom(_client):
        raise RuntimeError("schwab down")

    monkeypatch.setattr(eod, "fetch_accounts", _boom)

    with pytest.raises(RuntimeError):
        eod.run_snapshot_to(str(tmp_path), datetime.date(2026, 6, 4))
    assert list(tmp_path.iterdir()) == []  # never wrote a partial snapshot


# --------------------------------------------------------------------------- #
# Read-only guarantee (contract hard requirement)                            #
# --------------------------------------------------------------------------- #
def test_script_has_no_order_execution_references():
    source = _SCRIPT_PATH.read_text()
    forbidden = [
        "order_executor",
        "live_order_executor",
        "OrderExecutor",
        "strategy_runner",
        "place_order",
    ]
    offenders = [tok for tok in forbidden if tok in source]
    assert offenders == [], f"read-only violation: found {offenders}"
