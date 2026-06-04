# Portfolio EOD Snapshot — Contract (Jutsu-Labs writes → kurama reads)

**Writer (owner):** Jutsu-Labs — it owns Schwab auth/token. Implement the script there.
**Reader (consumer):** kurama (`~/dev/kurama`) — reads files only; never calls Schwab, holds no token.
**Why:** kurama runs a pre-market analysis each morning. To keep it incapable of trading, it must not hold Schwab creds or a trade-capable client. Jutsu-Labs exports an end-of-day snapshot to shared files that kurama reads.

---

## Read-only constraints (hard requirements)
- Use ONLY read calls already in the project — e.g. `client.get_account_numbers()` and `client.get_account(account_hash, fields=Account.Fields.POSITIONS)` (positions incl. options + balances), or the existing wrappers `LiveDataFetcher.fetch_account_positions()` / `fetch_account_equity()`.
- **Iterate every account** the login can see (all hashes from `get_account_numbers()`), not just `accounts[0]`. The owner has multiple accounts; emit all of them, each tagged with `account_id` (see below).
- Do **NOT** import or call anything under `jutsu_engine/live/order_executor*`, `live_order_executor`, `strategy_runner`, or `client.place_order(...)`. This script must never trade.
- No new Schwab scope required.

## Output location
Configurable dir (default `~/dev/kurama/data/portfolio/`):
- `positions-YYYY-MM-DD.csv` — dated; one row per position, across all accounts. **Append-only history** — never modify past dates.
- `account-YYYY-MM-DD.csv` — dated; **one row per account**.
- `latest.csv` / `latest-account.csv` — overwritten each run, **atomically** (write temp, then `os.replace()`), so kurama always has a stable "current" file.

### `positions` CSV columns
```
account_id,as_of_date,asset_type,symbol,quantity,average_price,market_value,underlying,option_type,strike,expiration,unrealized_pnl
```
- `account_id` — stable, non-secret account identifier (account number, its hash, or a masked/last-4 form). Consistent across both CSVs and across days. One row per position **per account**.
- `as_of_date` — YYYY-MM-DD (snapshot date)
- `asset_type` — `EQUITY` | `OPTION` (others as applicable)
- `symbol` — ticker, or the OCC option symbol for options
- `quantity` — signed (negative = short)
- `average_price` — cost basis per share/contract
- `market_value` — current market value of the position
- `underlying`,`option_type`(`CALL`|`PUT`),`strike`,`expiration`(YYYY-MM-DD) — options only; blank for equities
- `unrealized_pnl` — **open/unrealized** P/L (`longOpenProfitLoss` for longs, `shortOpenProfitLoss` for shorts); blank if Schwab omits it. Not day P/L.
- Extra columns are fine — kurama reads by header name and ignores unknowns.

### `account` CSV columns (one row per account)
```
account_id,as_of_date,total_equity,cash,buying_power,long_market_value,short_market_value
```
- `account_id` — matches the positions CSV.
- `total_equity` <- `currentBalances.liquidationValue` (net liquidation value); `cash` <- `cashBalance`; `buying_power` <- `buyingPower` (fallbacks as available).
- Use whatever balances `get_account` returns; **blank** (not `0`) for anything unavailable. Extra columns fine. kurama sums across rows for the portfolio total and can segment per account.

## Behavior
- **On-demand:** runnable as a CLI any time — `python scripts/eod_portfolio_snapshot.py` with flags `--date YYYY-MM-DD` (default today), `--out <dir>` (default the path above), `--dry-run` (print, don't write).
- **Scheduled:** ~16:15 ET on market days — use the project's `market_calendar` to skip weekends/holidays; launchd or cron.
- **Atomic writes:** temp file then `os.replace()` onto `latest*.csv` so kurama never reads a half-written file.
- **Idempotent:** re-running for a date overwrites that date's dated file (fine for intraday re-runs).
- **On failure** (auth/Schwab error): log and exit non-zero **without** overwriting `latest*.csv` — leave the prior good snapshot in place. Never write an empty/partial latest.

## kurama side (already built — for reference)
kurama reads `data/portfolio/latest.csv` + `latest-account.csv`, tagged by `account_id` (one row per account in `latest-account.csv`), sums `total_equity`/`cash` across accounts for the portfolio total, checks `as_of_date` freshness (flags stale/missing), and uses the web for live market context. It never triggers this script and never calls the brokerage.
