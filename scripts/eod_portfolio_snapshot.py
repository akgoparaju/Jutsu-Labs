#!/usr/bin/env python3
"""
EOD Portfolio Snapshot — Jutsu-Labs writer for the kurama read-only contract.

Exports an end-of-day snapshot of Schwab account positions and balances to CSV
files that kurama reads each morning. kurama never calls Schwab and never triggers
this script; it only reads the files this script writes.

Spec: docs/portfolio-snapshot-contract.md

READ-ONLY GUARANTEE:
    This script uses ONLY Schwab read calls (get_account_numbers, get_account with
    POSITIONS). It does NOT import or call any order-execution code and can never
    place a trade. See the contract's "Read-only constraints" section.

Usage:
    python scripts/eod_portfolio_snapshot.py                 # snapshot for today
    python scripts/eod_portfolio_snapshot.py --date 2026-06-04
    python scripts/eod_portfolio_snapshot.py --out /path/to/dir
    python scripts/eod_portfolio_snapshot.py --dry-run       # print, don't write
    python scripts/eod_portfolio_snapshot.py --ignore-market-calendar

Scheduled use (~16:15 ET on market days): a launchd/cron job invokes this script.
By default it skips weekends/holidays via the project's market calendar.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("EOD_PORTFOLIO_SNAPSHOT")

# Default output directory (kurama reads from here). Configurable via --out.
DEFAULT_OUT_DIR = Path.home() / "dev" / "kurama" / "data" / "portfolio"

# Schema per kurama's A1 decision (multi-account): positions carry `account_id`
# first; the account CSV is one row per account. `day_pnl` is an extra column
# kurama invited (A2) and ignores if unwanted.
POSITION_FIELDS = [
    "account_id",
    "as_of_date",
    "asset_type",
    "symbol",
    "quantity",
    "average_price",
    "market_value",
    "underlying",
    "option_type",
    "strike",
    "expiration",
    "unrealized_pnl",
    "day_pnl",
]

ACCOUNT_FIELDS = [
    "account_id",
    "as_of_date",
    "total_equity",
    "cash",
    "buying_power",
    "long_market_value",
    "short_market_value",
]

# OCC option symbol: <root><YYMMDD><C|P><strike*1000, 8 digits>.
# Schwab pads the root with spaces (e.g. "QQQ   251219P00300000").
_OCC_RE = re.compile(
    r"^(?P<root>[A-Za-z0-9./]+)\s*"
    r"(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
    r"(?P<cp>[CP])"
    r"(?P<strike>\d{8})$"
)


# --------------------------------------------------------------------------- #
# Pure parsing / formatting helpers                                           #
# --------------------------------------------------------------------------- #
def format_value(value) -> str:
    """Render a CSV cell value. None -> empty string; Decimal -> normalized."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        # Normalize so 300.000 -> 300, 150.500 -> 150.5 (avoids exponent form).
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            normalized = normalized.quantize(Decimal(1))
        return format(normalized, "f")
    return str(value)


def parse_occ_symbol(symbol: str) -> Optional[Dict[str, object]]:
    """Parse an OCC option symbol into its components.

    Returns dict with underlying/option_type/strike(Decimal)/expiration(YYYY-MM-DD),
    or None if `symbol` is not an OCC option symbol (e.g. a plain equity ticker).
    """
    if not symbol:
        return None
    match = _OCC_RE.match(symbol.strip())
    if not match:
        return None
    strike = (Decimal(match.group("strike")) / Decimal(1000))
    return {
        "underlying": match.group("root").strip(),
        "option_type": "CALL" if match.group("cp") == "C" else "PUT",
        "strike": strike,
        "expiration": f"20{match.group('yy')}-{match.group('mm')}-{match.group('dd')}",
    }


def _signed_quantity(pos: dict) -> Decimal:
    long_q = Decimal(str(pos.get("longQuantity", 0) or 0))
    short_q = Decimal(str(pos.get("shortQuantity", 0) or 0))
    return long_q - short_q


def _unrealized_pnl(pos: dict) -> Optional[float]:
    """Open (unrealized) P/L for the position, or None if Schwab didn't provide it."""
    long_q = pos.get("longQuantity", 0) or 0
    short_q = pos.get("shortQuantity", 0) or 0
    if long_q and pos.get("longOpenProfitLoss") is not None:
        return pos["longOpenProfitLoss"]
    if short_q and pos.get("shortOpenProfitLoss") is not None:
        return pos["shortOpenProfitLoss"]
    # Fall back to whichever open P/L field is present (covers zero-qty edge cases).
    if pos.get("longOpenProfitLoss") is not None:
        return pos["longOpenProfitLoss"]
    if pos.get("shortOpenProfitLoss") is not None:
        return pos["shortOpenProfitLoss"]
    return None


def position_to_row(pos: dict, as_of_date: str, account_id: str) -> Dict[str, str]:
    """Convert one Schwab position dict into a contract CSV row."""
    instrument = pos.get("instrument", {})
    asset_type = instrument.get("assetType", "")
    symbol = instrument.get("symbol", "")

    underlying = ""
    option_type = ""
    strike: Optional[Decimal] = None
    expiration = ""

    if asset_type == "OPTION":
        parsed = parse_occ_symbol(symbol)
        underlying = instrument.get("underlyingSymbol") or (
            parsed["underlying"] if parsed else ""
        )
        option_type = instrument.get("putCall") or (
            parsed["option_type"] if parsed else ""
        )
        if parsed:
            strike = parsed["strike"]
            expiration = parsed["expiration"]

    return {
        "account_id": account_id,
        "as_of_date": as_of_date,
        "asset_type": asset_type,
        "symbol": symbol,
        "quantity": format_value(_signed_quantity(pos)),
        "average_price": format_value(pos.get("averagePrice")),
        "market_value": format_value(pos.get("marketValue")),
        "underlying": format_value(underlying),
        "option_type": format_value(option_type),
        "strike": format_value(strike),
        "expiration": format_value(expiration),
        "unrealized_pnl": format_value(_unrealized_pnl(pos)),
        "day_pnl": format_value(pos.get("currentDayProfitLoss")),
    }


def extract_positions(
    account_json: dict, as_of_date: str, account_id: str
) -> List[Dict[str, str]]:
    """Build one CSV row per position for a single account's get_account payload."""
    securities_account = account_json["securitiesAccount"]
    positions = securities_account.get("positions", [])
    return [position_to_row(pos, as_of_date, account_id) for pos in positions]


def extract_account_row(
    account_json: dict, as_of_date: str, account_id: str
) -> Dict[str, str]:
    """Build the one-row balance summary for a single account."""
    securities_account = account_json["securitiesAccount"]
    balances = securities_account.get("currentBalances", {})

    def pick(*keys):
        for key in keys:
            if balances.get(key) is not None:
                return balances[key]
        return None

    return {
        "account_id": account_id,
        "as_of_date": as_of_date,
        "total_equity": format_value(pick("liquidationValue", "equity")),
        "cash": format_value(pick("cashBalance", "totalCash")),
        "buying_power": format_value(
            pick("buyingPower", "buyingPowerNonMarginableTrade")
        ),
        "long_market_value": format_value(pick("longMarketValue")),
        "short_market_value": format_value(pick("shortMarketValue")),
    }


def build_snapshot(
    accounts: List[Tuple[str, dict]], as_of_date: str
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Aggregate positions and per-account balances across all accounts.

    `accounts` is a list of (account_id, get_account_payload). Returns
    (position_rows across every account, one account_row per account).
    """
    position_rows: List[Dict[str, str]] = []
    account_rows: List[Dict[str, str]] = []
    for account_id, account_json in accounts:
        position_rows.extend(extract_positions(account_json, as_of_date, account_id))
        account_rows.append(extract_account_row(account_json, as_of_date, account_id))
    return position_rows, account_rows


# --------------------------------------------------------------------------- #
# CSV writing (atomic for latest*.csv)                                        #
# --------------------------------------------------------------------------- #
def _write_csv_atomic(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    """Write a CSV by writing a temp file in the same dir then os.replace().

    The atomic replace guarantees kurama never reads a half-written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp creates the temp file 0600; make the published CSV world-readable
        # so other users/services (e.g. Syncthing, kurama) can read it.
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        # Don't leave a stray temp file behind on failure.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def write_snapshot(
    out_dir,
    as_of_date: str,
    position_rows: List[Dict[str, str]],
    account_rows: List[Dict[str, str]],
) -> Dict[str, Path]:
    """Write the four contract files: dated positions/account + latest*.csv.

    Dated files are written per-date (idempotent overwrite for the same date,
    never touching other dates' history). latest*.csv are overwritten atomically.
    `account_rows` holds one row per account (kurama A1).
    """
    out_dir = Path(out_dir)
    paths = {
        "positions_dated": out_dir / f"positions-{as_of_date}.csv",
        "account_dated": out_dir / f"account-{as_of_date}.csv",
        "latest": out_dir / "latest.csv",
        "latest_account": out_dir / "latest-account.csv",
    }
    _write_csv_atomic(paths["positions_dated"], POSITION_FIELDS, position_rows)
    _write_csv_atomic(paths["account_dated"], ACCOUNT_FIELDS, account_rows)
    _write_csv_atomic(paths["latest"], POSITION_FIELDS, position_rows)
    _write_csv_atomic(paths["latest_account"], ACCOUNT_FIELDS, account_rows)
    return paths


# --------------------------------------------------------------------------- #
# Schwab read-only fetch (lazy imports; no order-execution code touched)      #
# --------------------------------------------------------------------------- #
def build_schwab_client():
    """Build an authenticated Schwab client using the project's existing token.

    Lazy-imports schwab so the pure logic above stays importable without the dep.
    """
    from dotenv import load_dotenv
    from schwab import auth

    load_dotenv()
    project_root = Path(__file__).resolve().parent.parent
    token_path_raw = os.getenv("SCHWAB_TOKEN_PATH", "token.json")
    if Path("/app").exists():
        token_path = Path("/app/data") / Path(token_path_raw).name
    else:
        token_path = project_root / token_path_raw

    if not token_path.exists():
        raise FileNotFoundError(
            f"Schwab token not found at {token_path}. Authenticate via the dashboard first."
        )

    client = auth.easy_client(
        api_key=os.getenv("SCHWAB_API_KEY"),
        app_secret=os.getenv("SCHWAB_API_SECRET"),
        callback_url=os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
        token_path=str(token_path),
    )
    logger.info("Schwab client initialized (token: %s)", token_path)
    return client


def fetch_accounts(client) -> List[Tuple[str, dict]]:
    """Fetch (account_id, get_account payload) for EVERY account. READ-ONLY.

    Iterates all account hashes from get_account_numbers() (kurama A1: snapshot
    all accounts, not just the first). `account_id` is the Schwab account hash —
    stable, deterministic, and not the literal account number (A1 blessed the hash).
    """
    from schwab.client import Client  # lazy import for the Fields enum

    accounts_response = client.get_account_numbers()
    if accounts_response.status_code != 200:
        raise RuntimeError(
            f"get_account_numbers returned status {accounts_response.status_code}"
        )
    accounts = accounts_response.json()
    if not accounts:
        raise RuntimeError("No Schwab accounts found")

    result: List[Tuple[str, dict]] = []
    for entry in accounts:
        account_hash = entry["hashValue"]
        account_response = client.get_account(
            account_hash, fields=Client.Account.Fields.POSITIONS
        )
        if account_response.status_code != 200:
            raise RuntimeError(
                f"get_account returned status {account_response.status_code}"
            )
        result.append((account_hash, account_response.json()))
    return result


# --------------------------------------------------------------------------- #
# Orchestration / CLI                                                         #
# --------------------------------------------------------------------------- #
def _is_trading_day(target_date: date) -> bool:
    """Defer to the project's market calendar (passing a date, not a datetime)."""
    from jutsu_engine.live.market_calendar import is_trading_day

    return is_trading_day(target_date)


def run_snapshot_to(out_dir, snapshot_date: Optional[date] = None) -> Dict[str, int]:
    """Fetch + build + write the snapshot to ``out_dir``. READ-ONLY.

    Importable entry point for in-process callers (e.g. the Docker EOD scheduler).
    Builds the snapshot fully BEFORE writing, so a Schwab failure raises without
    ever touching latest*.csv. Returns a small summary dict on success.
    """
    target = snapshot_date or date.today()
    as_of_date = target.isoformat()
    client = build_schwab_client()
    accounts = fetch_accounts(client)
    position_rows, account_rows = build_snapshot(accounts, as_of_date)
    write_snapshot(out_dir, as_of_date, position_rows, account_rows)
    return {
        "as_of_date": as_of_date,
        "accounts": len(account_rows),
        "positions": len(position_rows),
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export an EOD Schwab portfolio snapshot to CSV (read-only)."
    )
    parser.add_argument(
        "--date",
        help="Snapshot date YYYY-MM-DD (default: today).",
        default=None,
    )
    parser.add_argument(
        "--out",
        help=f"Output directory (default: {DEFAULT_OUT_DIR}).",
        default=str(DEFAULT_OUT_DIR),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the snapshot to stdout instead of writing files.",
    )
    parser.add_argument(
        "--ignore-market-calendar",
        action="store_true",
        help="Run even on weekends/holidays (skips the trading-day check).",
    )
    return parser.parse_args(argv)


def _resolve_date(date_arg: Optional[str]) -> date:
    if date_arg:
        return datetime.strptime(date_arg, "%Y-%m-%d").date()
    return date.today()


def _print_dry_run(as_of_date, position_rows, account_rows) -> None:
    print(f"# DRY RUN — snapshot for {as_of_date} (nothing written)")
    print("## positions")
    print(",".join(POSITION_FIELDS))
    for row in position_rows:
        print(",".join(row[k] for k in POSITION_FIELDS))
    print("## account")
    print(",".join(ACCOUNT_FIELDS))
    for row in account_rows:
        print(",".join(row[k] for k in ACCOUNT_FIELDS))


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    args = parse_args(argv)

    try:
        snapshot_date = _resolve_date(args.date)
    except ValueError:
        logger.error("Invalid --date %r (expected YYYY-MM-DD)", args.date)
        return 2

    as_of_date = snapshot_date.isoformat()

    # Scheduled runs skip non-trading days. On-demand callers can override.
    if not args.ignore_market_calendar and not args.dry_run:
        try:
            if not _is_trading_day(snapshot_date):
                logger.info("%s is not a trading day; skipping snapshot.", as_of_date)
                return 0
        except Exception as exc:  # calendar failure shouldn't crash an on-demand run
            logger.warning("Trading-day check failed (%s); proceeding anyway.", exc)

    # Fetch + build BEFORE any write so a failure leaves latest*.csv untouched.
    try:
        client = build_schwab_client()
        accounts = fetch_accounts(client)
        position_rows, account_rows = build_snapshot(accounts, as_of_date)
    except Exception as exc:
        logger.error("Snapshot failed (%s); leaving prior snapshot in place.", exc)
        return 1

    if args.dry_run:
        _print_dry_run(as_of_date, position_rows, account_rows)
        return 0

    try:
        paths = write_snapshot(args.out, as_of_date, position_rows, account_rows)
    except Exception as exc:
        logger.error("Failed writing snapshot files (%s).", exc)
        return 1

    logger.info(
        "Wrote %d positions across %d account(s) for %s to %s",
        len(position_rows),
        len(account_rows),
        as_of_date,
        paths["latest"].parent,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
