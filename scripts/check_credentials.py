#!/usr/bin/env python3
"""
Helper script to verify Schwab API credentials are properly configured.

Usage:
    python scripts/check_credentials.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_env_file():
    """Check if .env file exists."""
    env_file = project_root / '.env'

    if not env_file.exists():
        print("❌ .env file not found")
        print(f"   Expected location: {env_file}")
        print("\n💡 Solution:")
        print("   cp .env.example .env")
        print("   # Then edit .env with your actual credentials")
        return False

    print("✅ .env file exists")
    return True


def check_env_variables():
    """Check if environment variables are set."""
    # Load .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ python-dotenv loaded .env file")
    except ImportError:
        print("⚠️  python-dotenv not installed, checking system environment only")

    # Check required variables
    required_vars = {
        'SCHWAB_API_KEY': 'Schwab API Client ID',
        'SCHWAB_API_SECRET': 'Schwab API Secret',
        'SCHWAB_CALLBACK_URL': 'OAuth callback URL',
    }

    all_present = True
    for var_name, description in required_vars.items():
        value = os.getenv(var_name)

        if not value:
            print(f"❌ {var_name} not set")
            print(f"   Description: {description}")
            all_present = False
        elif value.startswith('your_') or value == 'your_api_key_here' or value == 'your_api_secret_here':
            print(f"⚠️  {var_name} has placeholder value")
            print(f"   Current: {value}")
            print(f"   You need to replace this with your actual credentials")
            all_present = False
        else:
            # Mask the actual value for security
            masked = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '****'
            print(f"✅ {var_name} = {masked}")

    return all_present


def check_database():
    """Check if database exists and has correct schema."""
    db_file = project_root / 'data' / 'market_data.db'

    if not db_file.exists():
        print("⚠️  Database not initialized")
        print("\n💡 Solution:")
        print("   jutsu init")
        return False

    print("✅ Database file exists")

    # Check schema
    try:
        from sqlalchemy import create_engine, inspect
        engine = create_engine(f'sqlite:///{db_file}')
        inspector = inspect(engine)

        tables = inspector.get_table_names()
        expected_tables = {'market_data', 'data_metadata', 'data_audit_log'}

        if expected_tables.issubset(set(tables)):
            print(f"✅ Database schema correct: {', '.join(sorted(tables))}")
            return True
        else:
            missing = expected_tables - set(tables)
            print(f"❌ Missing tables: {', '.join(missing)}")
            print("\n💡 Solution:")
            print("   jutsu init  # Recreate database schema")
            return False

    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return False


def test_api_connection():
    """Test Schwab API connection (if credentials are set)."""
    if not (os.getenv('SCHWAB_API_KEY') and os.getenv('SCHWAB_API_SECRET')):
        print("\n⏭️  Skipping API test (credentials not configured)")
        return True

    print("\n🔍 Testing Schwab API connection...")

    try:
        from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher

        fetcher = SchwabDataFetcher()
        print("✅ SchwabDataFetcher initialized")

        # Note: Actual API test would require OAuth flow
        print("ℹ️  Full API authentication test requires OAuth browser flow")
        print("   Run 'jutsu sync AAPL --start 2024-11-01' to test complete flow")

        return True

    except Exception as e:
        print(f"❌ Error initializing Schwab API: {e}")
        return False


def main():
    """Run all checks."""
    print("=" * 60)
    print("Jutsu Labs - Credentials Check")
    print("=" * 60)
    print()

    checks = {
        'Environment File': check_env_file(),
        'Environment Variables': check_env_variables(),
        'Database': check_database(),
        'API Connection': test_api_connection(),
    }

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)

    for check_name, result in checks.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{check_name:.<40} {status}")

    print()

    if all(checks.values()):
        print("🎉 All checks passed! You're ready to use Jutsu Labs")
        print()
        print("Next steps:")
        print("  1. jutsu sync AAPL --start 2024-01-01")
        print("  2. jutsu backtest AAPL --strategy SMA_Crossover")
        return 0
    else:
        print("⚠️  Some checks failed. Please fix the issues above.")
        print()
        print("Common solutions:")
        print("  • Missing .env: cp .env.example .env")
        print("  • Placeholder credentials: Edit .env with real API keys from https://developer.schwab.com")
        print("  • Database issues: jutsu init")
        return 1


if __name__ == '__main__':
    sys.exit(main())
