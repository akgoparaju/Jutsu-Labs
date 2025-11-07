"""
Trade logging for CSV export.

Captures comprehensive trade data including:
- Strategy state (indicators, thresholds, regime)
- Execution details (symbol, shares, price, commission)
- Portfolio state (cash, positions, allocation percentages)
- Decision rationale (why trade was made)

Two-phase logging:
1. Strategy phase: log_strategy_context() before signal generation
2. Execution phase: log_trade_execution() after Portfolio fills order
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from jutsu_engine.core.events import FillEvent

logger = logging.getLogger('PERFORMANCE.TRADE_LOGGER')


@dataclass
class StrategyContext:
    """
    Captures strategy state at signal generation time.
    
    Attributes:
        timestamp: When context was captured
        symbol: Symbol being analyzed (may differ from symbol traded)
        bar_number: Sequential bar count
        strategy_state: Human-readable state (e.g., "Regime 1: Strong Bullish")
        decision_reason: Why signal was generated
        indicator_values: Dict of indicator names → values (dynamic)
        threshold_values: Dict of threshold names → values (dynamic)
    """
    timestamp: datetime
    symbol: str
    bar_number: int
    strategy_state: str
    decision_reason: str
    indicator_values: Dict[str, Decimal] = field(default_factory=dict)
    threshold_values: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class TradeRecord:
    """
    Complete trade record combining strategy context and execution details.
    
    Matches user's required CSV columns:
    - Core trade data (ID, date, bar number, state, decision)
    - Indicator values (dynamic columns)
    - Thresholds (dynamic columns)
    - Order details (type, shares, price, commission)
    - Portfolio state (value, cash, allocation before/after)
    - Performance (cumulative return %)
    """
    # Core Trade Data
    trade_id: int
    date: datetime
    bar_number: int
    strategy_state: str
    ticker: str
    decision: str  # BUY/SELL/CLOSE
    decision_reason: str
    
    # Order Details
    order_type: str  # MARKET (MVP only)
    shares: int
    fill_price: Decimal
    position_value: Decimal  # shares × fill_price
    slippage: Decimal  # 0 in MVP
    commission: Decimal
    
    # Portfolio State
    portfolio_value_before: Decimal
    portfolio_value_after: Decimal
    cash_before: Decimal
    cash_after: Decimal
    
    # Performance
    cumulative_return_pct: Decimal
    
    # Indicator Values (dynamic - flattened from dict) - MUST BE AFTER NON-DEFAULT FIELDS
    indicator_values: Dict[str, Decimal] = field(default_factory=dict)
    
    # Thresholds (dynamic - flattened from dict) - MUST BE AFTER NON-DEFAULT FIELDS
    threshold_values: Dict[str, Decimal] = field(default_factory=dict)
    
    # Portfolio Allocation (Dict fields) - MUST BE AFTER NON-DEFAULT FIELDS
    allocation_before: Dict[str, Decimal] = field(default_factory=dict)  # {symbol: percent}
    allocation_after: Dict[str, Decimal] = field(default_factory=dict)


class TradeLogger:
    """
    Captures trade data for CSV export.
    
    Two-phase logging:
    1. Strategy phase: log_strategy_context() - indicators, thresholds, regime
    2. Execution phase: log_trade_execution() - portfolio state, fill details
    
    Correlation: Match strategy context to trade via (symbol, timestamp) proximity.
    
    Example:
        >>> logger = TradeLogger(initial_capital=Decimal('10000'))
        >>> logger.increment_bar()  # Called by EventLoop on each bar
        >>> logger.log_strategy_context(
        ...     timestamp=datetime.now(),
        ...     symbol='QQQ',
        ...     strategy_state='Regime 1: Strong Bullish',
        ...     decision_reason='EMA crossover AND ADX > 25',
        ...     indicator_values={'EMA_fast': Decimal('150.2'), 'ADX': Decimal('28.5')},
        ...     threshold_values={'adx_threshold_high': Decimal('25')}
        ... )
        >>> logger.log_trade_execution(
        ...     fill=fill_event,
        ...     portfolio_value_before=Decimal('10000'),
        ...     portfolio_value_after=Decimal('9500'),
        ...     cash_before=Decimal('10000'),
        ...     cash_after=Decimal('5000'),
        ...     allocation_before={'CASH': Decimal('100')},
        ...     allocation_after={'TQQQ': Decimal('47.8'), 'CASH': Decimal('52.2')}
        ... )
        >>> df = logger.to_dataframe()
        >>> df.to_csv('trades.csv', index=False)
    """
    
    def __init__(self, initial_capital: Decimal):
        """
        Initialize TradeLogger.
        
        Args:
            initial_capital: Starting portfolio value for cumulative return calculation
        """
        self._initial_capital = initial_capital
        self._trade_counter = 0
        self._bar_counter = 0
        
        # Storage
        self._strategy_contexts: List[StrategyContext] = []
        self._trade_records: List[TradeRecord] = []
        
        logger.info(f"TradeLogger initialized with initial_capital={initial_capital}")
    
    def increment_bar(self) -> None:
        """
        Increment bar counter.
        
        Called by EventLoop on each bar to track sequential bar numbers.
        """
        self._bar_counter += 1
    
    def log_strategy_context(
        self,
        timestamp: datetime,
        symbol: str,
        strategy_state: str,
        decision_reason: str,
        indicator_values: Dict[str, Decimal],
        threshold_values: Dict[str, Decimal]
    ) -> None:
        """
        Log strategy context BEFORE signal generation.
        
        Called by Strategy in on_bar() when decision is made.
        Captures indicators, thresholds, and regime at decision time.
        
        Args:
            timestamp: When context was captured
            symbol: Symbol being analyzed (signal asset)
            strategy_state: Human-readable state (e.g., "Regime 1: Strong Bullish")
            decision_reason: Why signal was generated (e.g., "EMA crossover AND ADX > 25")
            indicator_values: Dict of indicator names → Decimal values
            threshold_values: Dict of threshold names → Decimal values
        """
        context = StrategyContext(
            timestamp=timestamp,
            symbol=symbol,
            bar_number=self._bar_counter,
            strategy_state=strategy_state,
            decision_reason=decision_reason,
            indicator_values=indicator_values.copy(),
            threshold_values=threshold_values.copy()
        )
        self._strategy_contexts.append(context)
        
        logger.debug(
            f"Logged strategy context: bar={self._bar_counter}, "
            f"symbol={symbol}, state={strategy_state}, "
            f"indicators={list(indicator_values.keys())}"
        )
    
    def log_trade_execution(
        self,
        fill: FillEvent,
        portfolio_value_before: Decimal,
        portfolio_value_after: Decimal,
        cash_before: Decimal,
        cash_after: Decimal,
        allocation_before: Dict[str, Decimal],
        allocation_after: Dict[str, Decimal]
    ) -> None:
        """
        Log trade execution AFTER Portfolio.execute_signal().
        
        Matches with most recent StrategyContext for this symbol.
        Creates complete TradeRecord with all required data.
        
        Args:
            fill: FillEvent with execution details
            portfolio_value_before: Portfolio value before trade
            portfolio_value_after: Portfolio value after trade
            cash_before: Cash balance before trade
            cash_after: Cash balance after trade
            allocation_before: Dict of symbol → allocation % before trade
            allocation_after: Dict of symbol → allocation % after trade
        """
        # Find matching strategy context
        context = self._find_matching_context(fill.symbol, fill.timestamp)
        
        # Calculate cumulative return
        current_value = portfolio_value_after
        cumulative_return = (
            (current_value - self._initial_capital) / self._initial_capital
        ) * Decimal('100')
        
        # Create trade record
        self._trade_counter += 1
        record = TradeRecord(
            trade_id=self._trade_counter,
            date=fill.timestamp,
            bar_number=context.bar_number if context else self._bar_counter,
            strategy_state=context.strategy_state if context else "Unknown",
            ticker=fill.symbol,
            decision=fill.direction,  # BUY/SELL
            decision_reason=context.decision_reason if context else "No context available",
            indicator_values=context.indicator_values.copy() if context else {},
            threshold_values=context.threshold_values.copy() if context else {},
            order_type="MARKET",
            shares=fill.quantity,
            fill_price=fill.fill_price,
            position_value=fill.fill_price * Decimal(fill.quantity),
            slippage=Decimal('0'),  # MVP: no slippage
            commission=fill.commission,
            portfolio_value_before=portfolio_value_before,
            portfolio_value_after=portfolio_value_after,
            cash_before=cash_before,
            cash_after=cash_after,
            allocation_before=allocation_before.copy(),
            allocation_after=allocation_after.copy(),
            cumulative_return_pct=cumulative_return
        )
        
        self._trade_records.append(record)
        
        logger.info(
            f"Trade #{self._trade_counter}: {fill.direction} {fill.quantity} "
            f"{fill.symbol} @ ${fill.fill_price}, "
            f"portfolio_value: ${portfolio_value_before} → ${portfolio_value_after}, "
            f"return: {cumulative_return:.2f}%"
        )
    
    def _find_matching_context(
        self,
        symbol: str,
        timestamp: datetime
    ) -> Optional[StrategyContext]:
        """
        Find most recent StrategyContext for this symbol.
        
        Matching strategy:
        1. Filter by symbol (exact match)
        2. Filter by timestamp (within same bar - tolerance 60 seconds)
        3. Return most recent match
        
        Note: For signal asset pattern (e.g., QQQ signal → TQQQ trade),
        exact symbol matching may not find context. Future enhancement:
        add signal_asset tracking or fuzzy matching.
        
        Args:
            symbol: Symbol to match
            timestamp: Timestamp to match (within tolerance)
        
        Returns:
            Most recent matching StrategyContext or None if no match
        """
        matches = [
            ctx for ctx in self._strategy_contexts
            if ctx.symbol == symbol
            and abs((ctx.timestamp - timestamp).total_seconds()) < 60
        ]
        
        if not matches:
            logger.warning(
                f"No strategy context found for {symbol} at {timestamp}. "
                f"Trade record will have 'Unknown' state and 'No context' reason."
            )
            return None
        
        return matches[-1]
    
    def get_trade_records(self) -> List[TradeRecord]:
        """
        Get all trade records.
        
        Returns:
            Copy of all trade records (for safety)
        """
        return self._trade_records.copy()
    
    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert trade records to DataFrame for CSV export.
        
        Handles dynamic columns (indicators, thresholds, allocations).
        Column order matches user specification:
        1. Core trade data
        2. Indicator values (dynamic)
        3. Thresholds (dynamic)
        4. Order details
        5. Portfolio state
        6. Performance
        
        Returns:
            DataFrame with all trade records and dynamic columns
            
        Raises:
            ValueError: If no trade records exist
        """
        if not self._trade_records:
            logger.warning("No trade records to export")
            return pd.DataFrame()
        
        # Extract all indicator names across all records
        all_indicators = set()
        for record in self._trade_records:
            all_indicators.update(record.indicator_values.keys())
        
        # Extract all threshold names
        all_thresholds = set()
        for record in self._trade_records:
            all_thresholds.update(record.threshold_values.keys())
        
        logger.debug(
            f"Building DataFrame: {len(self._trade_records)} records, "
            f"{len(all_indicators)} indicators, {len(all_thresholds)} thresholds"
        )
        
        # Build DataFrame rows
        rows = []
        for record in self._trade_records:
            row = {
                'Trade_ID': record.trade_id,
                'Date': record.date,
                'Bar_Number': record.bar_number,
                'Strategy_State': record.strategy_state,
                'Ticker': record.ticker,
                'Decision': record.decision,
                'Decision_Reason': record.decision_reason,
            }
            
            # Add indicator columns (dynamic, sorted for consistency)
            for ind_name in sorted(all_indicators):
                value = record.indicator_values.get(ind_name, None)
                row[f'Indicator_{ind_name}'] = float(value) if value is not None else None
            
            # Add threshold columns (dynamic, sorted for consistency)
            for thresh_name in sorted(all_thresholds):
                value = record.threshold_values.get(thresh_name, None)
                row[f'Threshold_{thresh_name}'] = float(value) if value is not None else None
            
            # Add order details
            row.update({
                'Order_Type': record.order_type,
                'Shares': record.shares,
                'Fill_Price': float(record.fill_price),
                'Position_Value': float(record.position_value),
                'Slippage': float(record.slippage),
                'Commission': float(record.commission),
            })
            
            # Add portfolio state
            row.update({
                'Portfolio_Value_Before': float(record.portfolio_value_before),
                'Portfolio_Value_After': float(record.portfolio_value_after),
                'Cash_Before': float(record.cash_before),
                'Cash_After': float(record.cash_after),
            })
            
            # Add allocation (formatted as "TQQQ: 60.0%, CASH: 40.0%")
            row['Allocation_Before'] = self._format_allocation(record.allocation_before)
            row['Allocation_After'] = self._format_allocation(record.allocation_after)
            
            # Add performance
            row['Cumulative_Return_Pct'] = float(record.cumulative_return_pct)
            
            rows.append(row)
        
        df = pd.DataFrame(rows)
        logger.info(f"Generated DataFrame: {len(df)} rows, {len(df.columns)} columns")
        
        return df
    
    def _format_allocation(self, allocation: Dict[str, Decimal]) -> str:
        """
        Format allocation dict as percentage string.
        
        Example: {'TQQQ': Decimal('60'), 'CASH': Decimal('40')} 
                 → "CASH: 40.0%, TQQQ: 60.0%"
        
        Args:
            allocation: Dict of symbol → allocation percentage (0-100)
        
        Returns:
            Formatted string with allocations sorted alphabetically
        """
        if not allocation:
            return "CASH: 100.0%"
        
        # Sort alphabetically for consistency (CASH typically first)
        parts = [
            f"{symbol}: {float(pct):.1f}%"
            for symbol, pct in sorted(allocation.items())
        ]
        return ", ".join(parts)
