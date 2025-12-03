"""
Live Data Fetcher Module

Purpose:
    Fetch historical bars, live quotes, and create synthetic daily bars.
    Validates corporate actions (splits, dividends).

Dependencies:
    - schwab-py>=1.5.0
    - pandas>=2.0.0

Usage:
    from jutsu_engine.live import LiveDataFetcher

    fetcher = LiveDataFetcher(schwab_client)
    hist_df = fetcher.fetch_historical_bars('QQQ', lookback=250)
    quote = fetcher.fetch_current_quote('QQQ')
    synthetic = fetcher.create_synthetic_daily_bar(hist_df, quote)
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List

import pandas as pd

logger = logging.getLogger('LIVE.DATA_FETCHER')


class DataFetchError(Exception):
    """Raised when data fetching fails."""
    pass


class CorporateActionDetected(Exception):
    """Raised when split/dividend detected (>20% price drop)."""
    pass


class LiveDataFetcher:
    """Fetch live market data and create synthetic daily bars."""

    def __init__(self, client):
        """
        Initialize with authenticated Schwab client.

        Args:
            client: schwab.Client instance
        """
        self.client = client

    def fetch_historical_bars(self, symbol: str, lookback: int = 250) -> pd.DataFrame:
        """
        Fetch historical daily bars for last N trading days.

        Args:
            symbol: Ticker symbol (e.g., 'QQQ')
            lookback: Number of trading days to fetch (default 250)

        Returns:
            DataFrame with columns: date, open, high, low, close, volume

        Raises:
            DataFetchError: If API call fails or returns incomplete data
        """
        logger.info(f"Fetching {lookback} bars for {symbol}")

        try:
            response = self.client.get_price_history(
                symbol,
                period_type=self.client.PriceHistory.PeriodType.YEAR,
                period=self.client.PriceHistory.Period.TWENTY_YEARS,
                frequency_type=self.client.PriceHistory.FrequencyType.DAILY,
                frequency=self.client.PriceHistory.Frequency.DAILY
            )

            if response.status_code != 200:
                raise DataFetchError(f"API returned status {response.status_code}")

            data = response.json()

            if 'candles' not in data or not data['candles']:
                raise DataFetchError(f"No candle data received for {symbol}")

            # Parse response into DataFrame
            candles = data['candles']
            df = pd.DataFrame(candles)

            # Convert timestamp to datetime
            df['date'] = pd.to_datetime(df['datetime'], unit='ms', utc=True)

            # Select required columns
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]

            # Keep only requested number of bars
            df = df.tail(lookback)

            if len(df) < lookback * 0.95:  # Allow 5% tolerance
                logger.warning(f"Received {len(df)} bars, expected ~{lookback}")

            logger.info(f"Retrieved {len(df)} bars for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch historical bars for {symbol}: {e}")
            raise DataFetchError(f"Historical data fetch failed: {e}")

    def fetch_current_quote(self, symbol: str) -> Decimal:
        """
        Fetch current quote (last price) for symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Last price as Decimal

        Raises:
            DataFetchError: If quote fetch fails
        """
        logger.debug(f"Fetching quote for {symbol}")

        try:
            response = self.client.get_quote(symbol)

            if response.status_code != 200:
                raise DataFetchError(f"Quote API returned status {response.status_code}")

            data = response.json()

            if symbol not in data:
                raise DataFetchError(f"Symbol {symbol} not in response")

            quote_data = data[symbol].get('quote', {})
            last_price = quote_data.get('lastPrice')

            if last_price is None:
                raise DataFetchError(f"No lastPrice in quote for {symbol}")

            price_decimal = Decimal(str(last_price))
            logger.debug(f"Quote for {symbol}: ${price_decimal:.2f}")

            return price_decimal

        except Exception as e:
            logger.error(f"Failed to fetch quote for {symbol}: {e}")
            raise DataFetchError(f"Quote fetch failed: {e}")

    def fetch_all_quotes(self, symbols: List[str]) -> Dict[str, Decimal]:
        """
        Fetch quotes for multiple symbols.

        Args:
            symbols: List of ticker symbols

        Returns:
            Dict mapping symbol to last price

        Raises:
            DataFetchError: If any quote fetch fails
        """
        logger.info(f"Fetching quotes for {len(symbols)} symbols: {symbols}")

        quotes = {}
        for symbol in symbols:
            quotes[symbol] = self.fetch_current_quote(symbol)

        logger.info(f"Successfully fetched all {len(quotes)} quotes")
        return quotes

    def create_synthetic_daily_bar(
        self,
        historical_df: pd.DataFrame,
        current_quote: Decimal
    ) -> pd.DataFrame:
        """
        Create synthetic daily bar by appending current quote as "close".

        Args:
            historical_df: Historical bars (N-1 days)
            current_quote: Current quote (15:55 price)

        Returns:
            DataFrame with N bars (historical + synthetic today)

        Note:
            Synthetic bar uses quote as all OHLC values since we don't
            have intraday data. Volume is set to 0 (unknown at 15:55).
        """
        today = datetime.now(timezone.utc).date()

        logger.debug(f"Creating synthetic bar for {today} with quote={current_quote}")

        # Create synthetic bar for today
        synthetic_bar = pd.DataFrame([{
            'date': pd.Timestamp(today, tz='UTC'),
            'open': float(current_quote),
            'high': float(current_quote),
            'low': float(current_quote),
            'close': float(current_quote),
            'volume': 0  # Volume unknown at 15:55
        }])

        # Append to historical
        combined_df = pd.concat([historical_df, synthetic_bar], ignore_index=True)

        logger.info(f"Created synthetic bar: close=${current_quote:.2f}, total bars={len(combined_df)}")

        return combined_df

    def validate_corporate_actions(self, df: pd.DataFrame, threshold_pct: float = 0.20) -> bool:
        """
        Detect potential splits/dividends (>20% price drop).

        Args:
            df: DataFrame with historical bars
            threshold_pct: Price drop threshold (default 20%)

        Returns:
            True if no corporate actions detected, False otherwise

        Raises:
            CorporateActionDetected: If price drop exceeds threshold
        """
        logger.debug(f"Validating corporate actions (threshold={threshold_pct:.1%})")

        # Calculate day-to-day percentage changes
        df_copy = df.copy()
        df_copy['pct_change'] = df_copy['close'].pct_change()

        # Find maximum price drop
        max_drop = df_copy['pct_change'].min()

        if max_drop < -threshold_pct:
            logger.error(f"Corporate action detected: {max_drop:.2%} drop exceeds {threshold_pct:.1%} threshold")
            raise CorporateActionDetected(f"Price drop {max_drop:.2%} suggests split/dividend")

        logger.info(f"Corporate action validation: PASSED (max drop: {max_drop:.2%})")
        return True

    def fetch_account_equity(self) -> Decimal:
        """
        Fetch current account equity value.

        Returns:
            Account equity as Decimal

        Raises:
            DataFetchError: If account fetch fails
        """
        logger.debug("Fetching account equity")

        try:
            # Get account numbers
            accounts_response = self.client.get_account_numbers()

            if accounts_response.status_code != 200:
                raise DataFetchError(f"Account API returned status {accounts_response.status_code}")

            accounts = accounts_response.json()

            if not accounts:
                raise DataFetchError("No accounts found")

            # Use first account
            account_hash = accounts[0]['hashValue']

            # Get account details
            account_response = self.client.get_account(
                account_hash,
                fields=self.client.Account.Fields.POSITIONS
            )

            if account_response.status_code != 200:
                raise DataFetchError(f"Account details API returned status {account_response.status_code}")

            account_data = account_response.json()
            equity = account_data['securitiesAccount']['currentBalances']['liquidationValue']

            equity_decimal = Decimal(str(equity))
            logger.info(f"Account equity: ${equity_decimal:,.2f}")

            return equity_decimal

        except Exception as e:
            logger.error(f"Failed to fetch account equity: {e}")
            raise DataFetchError(f"Account equity fetch failed: {e}")

    def fetch_account_positions(self) -> Dict[str, int]:
        """
        Fetch current account positions.

        Returns:
            Dict mapping symbol to share quantity

        Raises:
            DataFetchError: If position fetch fails
        """
        logger.debug("Fetching account positions")

        try:
            # Get account numbers
            accounts_response = self.client.get_account_numbers()

            if accounts_response.status_code != 200:
                raise DataFetchError(f"Account API returned status {accounts_response.status_code}")

            accounts = accounts_response.json()

            if not accounts:
                raise DataFetchError("No accounts found")

            # Use first account
            account_hash = accounts[0]['hashValue']

            # Get account with positions
            account_response = self.client.get_account(
                account_hash,
                fields=self.client.Account.Fields.POSITIONS
            )

            if account_response.status_code != 200:
                raise DataFetchError(f"Account details API returned status {account_response.status_code}")

            account_data = account_response.json()
            positions_data = account_data['securitiesAccount'].get('positions', [])

            # Parse positions
            positions = {}
            for pos in positions_data:
                symbol = pos['instrument']['symbol']
                quantity = int(pos['longQuantity'])  # Whole shares only
                positions[symbol] = quantity

            logger.info(f"Fetched {len(positions)} positions from account")
            return positions

        except Exception as e:
            logger.error(f"Failed to fetch account positions: {e}")
            raise DataFetchError(f"Position fetch failed: {e}")
