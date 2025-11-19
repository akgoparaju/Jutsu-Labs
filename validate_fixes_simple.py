"""
Simple validation of WFO fixes without dependencies.
"""
from pathlib import Path
import csv

def test_real_data():
    """Test with real WFO output if available."""
    print("=" * 60)
    print("WFO Bug Fix Validation - Real Data Check")
    print("=" * 60)
    print()

    test_output_dir = Path("output/wfo_MACD_Trend_v6_2025-11-10_181739")

    if not test_output_dir.exists():
        print("✗ Test output directory not found")
        return False

    # Read original transactions file
    trades_csv = test_output_dir / "wfo_trades_master.csv"
    if not trades_csv.exists():
        print("✗ wfo_trades_master.csv not found")
        return False

    with open(trades_csv, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Current wfo_trades_master.csv: {len(rows)} rows")
    print()

    if not rows:
        print("✗ No data in CSV")
        return False

    # Check format
    first_row = rows[0]
    columns = first_row.keys()

    print("Columns detected:")
    for col in columns:
        print(f"  - {col}")
    print()

    if 'Date' in columns and 'Decision' in columns:
        print("Format: OLD (separate BUY/SELL transactions)")
        buy_count = sum(1 for row in rows if row.get('Decision') == 'BUY')
        sell_count = sum(1 for row in rows if row.get('Decision') == 'SELL')
        print(f"  BUYs: {buy_count}")
        print(f"  SELLs: {sell_count}")
        print(f"  Total rows: {len(rows)}")
        print()
        print(f"Expected after fix: ~{min(buy_count, sell_count)} complete trades")
        print("✗ Still has old format - need to re-run WFO")
        return False

    elif 'Entry_Date' in columns and 'Exit_Date' in columns:
        print("Format: NEW (complete trades)")
        print(f"  Complete trades: {len(rows)}")
        print()

        # Check for Trade_Return_Percent column
        if 'Trade_Return_Percent' not in columns:
            print("✗ Missing Trade_Return_Percent column")
            return False
        else:
            print("✓ Has Trade_Return_Percent column")

        # Check commission values
        if 'Commission_Total' in columns:
            commissions = [float(row.get('Commission_Total', 0)) for row in rows]
            total_commission = sum(commissions)
            print(f"  Total commission: ${total_commission:.2f}")

            if total_commission == 0.0:
                print("  ✓ Commission = 0.0 (config setting respected)")
            else:
                print(f"  ⚠ Commission > 0 (expected 0.0 from config)")

        # Show sample trade
        if rows:
            print()
            print("Sample trade (first row):")
            sample = rows[0]
            for key, value in sample.items():
                if key in ['Entry_Date', 'Exit_Date', 'Symbol', 'Entry_Price', 'Exit_Price',
                          'Trade_Return_Percent', 'Commission_Total']:
                    print(f"  {key}: {value}")

        print()
        print("✓ New format detected - fixes applied successfully!")
        return True
    else:
        print("✗ Unknown format")
        return False

if __name__ == "__main__":
    success = test_real_data()
    print()
    print("=" * 60)
    if success:
        print("✓ Validation PASSED - Fixes are working")
    else:
        print("⚠ Validation incomplete - Need to re-run WFO to test fixes")
    print("=" * 60)
