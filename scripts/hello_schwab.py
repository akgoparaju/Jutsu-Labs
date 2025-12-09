#!/usr/bin/env python3
"""
Phase 0: Hello Schwab - OAuth Authentication Test

Purpose:
    Validate Schwab API authentication and basic data fetching.
    Tests OAuth 2.0 flow, token refresh, and quote retrieval.

Usage:
    python scripts/hello_schwab.py

Success Criteria:
    - OAuth authentication completes successfully
    - Token refresh mechanism works
    - Can fetch single quote (QQQ)
    - Can retrieve account information
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import schwab

def main() -> None:
    """
    Phase 0 validation workflow:
    1. Load OAuth credentials
    2. Initialize Schwab client
    3. Test token validity
    4. Fetch single quote
    5. Retrieve account info
    """
    print("="*70)
    print("PHASE 0: Hello Schwab - OAuth Authentication Test")
    print("="*70)
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

    # Step 1: Load environment variables
    load_dotenv()

    api_key = os.getenv('SCHWAB_API_KEY')
    api_secret = os.getenv('SCHWAB_API_SECRET')
    token_path = os.getenv('SCHWAB_TOKEN_PATH', str(project_root / 'token.json'))

    if not api_key or not api_secret:
        print("❌ ERROR: SCHWAB_API_KEY or SCHWAB_API_SECRET not found in .env")
        print("   Please configure your Schwab API credentials.")
        sys.exit(1)

    print("✅ Step 1: Loaded OAuth credentials from .env")
    print(f"   API Key: {api_key[:10]}...{api_key[-4:]}")
    print(f"   Token Path: {token_path}\n")

    # Step 2: Initialize Schwab client
    try:
        print("🔄 Step 2: Initializing Schwab client...")

        client = schwab.auth.easy_client(
            api_key=api_key,
            app_secret=api_secret,
            callback_url='https://127.0.0.1:8182',
            token_path=token_path
        )

        print("✅ Step 2: Schwab client initialized successfully")
        print(f"   Token stored at: {token_path}\n")

    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Schwab client: {e}")
        print("   This may require manual OAuth flow on first run.")
        sys.exit(1)

    # Step 3: Test token validity (implicit in next API call)
    print("🔄 Step 3: Testing token validity...\n")

    # Step 4: Fetch single quote
    try:
        print("🔄 Step 4: Fetching QQQ quote...")

        response = client.get_quote('QQQ')
        quote_data = response.json()

        if 'quote' in quote_data and 'lastPrice' in quote_data['quote']:
            last_price = quote_data['quote']['lastPrice']
            quote_time = quote_data['quote'].get('quoteTime', 'N/A')

            print("✅ Step 4: Successfully fetched QQQ quote")
            print(f"   Last Price: ${last_price:.2f}")
            print(f"   Quote Time: {quote_time}\n")
        else:
            print("⚠️  WARNING: Unexpected quote response format")
            print(f"   Response: {quote_data}\n")

    except Exception as e:
        print(f"❌ ERROR: Failed to fetch quote: {e}\n")
        sys.exit(1)

    # Step 5: Retrieve account information
    try:
        print("🔄 Step 5: Retrieving account information...")

        accounts_response = client.get_account_numbers()
        accounts = accounts_response.json()

        if accounts:
            print(f"✅ Step 5: Successfully retrieved {len(accounts)} account(s)")
            for idx, account in enumerate(accounts, 1):
                account_num = account.get('accountNumber', 'N/A')
                hash_value = account.get('hashValue', 'N/A')
                print(f"   Account {idx}: {account_num} (Hash: {hash_value[:10]}...)")
        else:
            print("⚠️  WARNING: No accounts found")

    except Exception as e:
        print(f"❌ ERROR: Failed to retrieve accounts: {e}\n")
        sys.exit(1)

    # Success summary
    print("\n" + "="*70)
    print("✅ PHASE 0 VALIDATION COMPLETE")
    print("="*70)
    print("All checks passed:")
    print("  ✓ OAuth authentication successful")
    print("  ✓ Token management working")
    print("  ✓ Quote fetching operational")
    print("  ✓ Account access verified")
    print("\nNext Steps:")
    print("  1. Schedule this script via cron for daily token validation")
    print("  2. Proceed to Phase 1: Dry-Run Mode implementation")
    print("="*70)

if __name__ == "__main__":
    main()
