"""
Trades API Routes

GET /api/trades - Get trade history (paginated)
GET /api/trades/export - Export trades as CSV
POST /api/trades/execute - Execute a trade (Jutsu Trader)
"""

import logging
import io
import csv
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from jutsu_engine.api.schemas import (
    TradeRecord,
    TradeListResponse,
    ErrorResponse,
    ExecuteTradeRequest,
    ExecuteTradeResponse,
)
from jutsu_engine.api.dependencies import (
    get_db,
    verify_credentials,
    require_permission,
    get_engine_state,
    load_config,
)
from jutsu_engine.data.models import LiveTrade

logger = logging.getLogger('API.TRADES')

router = APIRouter(prefix="/api/trades", tags=["trades"])

# Valid symbols for trading
VALID_SYMBOLS = {'QQQ', 'TQQQ', 'PSQ', 'TMF', 'TMV', 'TLT'}


@router.get(
    "",
    response_model=TradeListResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get trade history",
    description="Returns paginated trade history with optional filtering."
)
async def get_trades(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    action: Optional[str] = Query(None, description="Filter by action (BUY/SELL)"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    _auth: bool = Depends(verify_credentials),
) -> TradeListResponse:
    """
    Get paginated trade history.

    Supports filtering by:
    - symbol: Stock symbol
    - mode: Trading mode (offline_mock, online_live)
    - action: Trade action (BUY, SELL)
    - start_date/end_date: Date range
    """
    try:
        # Build query with filters
        query = db.query(LiveTrade)

        filters = []

        if symbol:
            filters.append(LiveTrade.symbol == symbol.upper())

        if mode:
            filters.append(LiveTrade.mode == mode)

        if action:
            filters.append(LiveTrade.action == action.upper())

        if start_date:
            filters.append(LiveTrade.timestamp >= start_date)

        if end_date:
            filters.append(LiveTrade.timestamp <= end_date)

        if filters:
            query = query.filter(and_(*filters))

        # Get total count
        total = query.count()

        # Calculate pagination
        total_pages = (total + page_size - 1) // page_size
        offset = (page - 1) * page_size

        # Get paginated results
        trades = query.order_by(desc(LiveTrade.timestamp)) \
                      .offset(offset) \
                      .limit(page_size) \
                      .all()

        # Convert to response models
        trade_records = []
        for trade in trades:
            trade_records.append(TradeRecord(
                id=trade.id,
                symbol=trade.symbol,
                timestamp=trade.timestamp,
                action=trade.action,
                quantity=trade.quantity,
                target_price=float(trade.target_price) if trade.target_price else 0.0,
                fill_price=float(trade.fill_price) if trade.fill_price else None,
                fill_value=float(trade.fill_value) if trade.fill_value else None,
                slippage_pct=float(trade.slippage_pct) if trade.slippage_pct is not None else 0.0,
                schwab_order_id=trade.schwab_order_id,
                strategy_cell=trade.strategy_cell,
                trend_state=trade.trend_state,
                vol_state=trade.vol_state,
                t_norm=float(trade.t_norm) if trade.t_norm else None,
                z_score=float(trade.z_score) if trade.z_score else None,
                reason=trade.reason,
                mode=trade.mode,
            ))

        return TradeListResponse(
            trades=trade_records,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    except Exception as e:
        logger.error(f"Trades list error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export",
    response_class=StreamingResponse,
    summary="Export trades as CSV",
    description="Export all trades matching filters as a CSV file."
)
async def export_trades(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    action: Optional[str] = Query(None, description="Filter by action (BUY/SELL)"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    _auth: bool = Depends(verify_credentials),
):
    """
    Export trades as CSV file.

    Returns a downloadable CSV with all trades matching the filters.
    """
    try:
        # Build query with filters
        query = db.query(LiveTrade)

        filters = []

        if symbol:
            filters.append(LiveTrade.symbol == symbol.upper())

        if mode:
            filters.append(LiveTrade.mode == mode)

        if action:
            filters.append(LiveTrade.action == action.upper())

        if start_date:
            filters.append(LiveTrade.timestamp >= start_date)

        if end_date:
            filters.append(LiveTrade.timestamp <= end_date)

        if filters:
            query = query.filter(and_(*filters))

        # Get all matching trades
        trades = query.order_by(desc(LiveTrade.timestamp)).all()

        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'id',
            'timestamp',
            'symbol',
            'action',
            'quantity',
            'target_price',
            'fill_price',
            'fill_value',
            'slippage_pct',
            'schwab_order_id',
            'strategy_cell',
            'trend_state',
            'vol_state',
            't_norm',
            'z_score',
            'reason',
            'mode',
        ])

        # Write data rows
        for trade in trades:
            writer.writerow([
                trade.id,
                trade.timestamp.isoformat() if trade.timestamp else '',
                trade.symbol,
                trade.action,
                trade.quantity,
                float(trade.target_price) if trade.target_price else '',
                float(trade.fill_price) if trade.fill_price else '',
                float(trade.fill_value) if trade.fill_value else '',
                float(trade.slippage_pct) if trade.slippage_pct else '',
                trade.schwab_order_id or '',
                trade.strategy_cell or '',
                trade.trend_state or '',
                trade.vol_state or '',
                float(trade.t_norm) if trade.t_norm else '',
                float(trade.z_score) if trade.z_score else '',
                trade.reason or '',
                trade.mode,
            ])

        # Generate filename
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"trades_export_{timestamp}.csv"

        # Return streaming response
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        logger.error(f"Trades export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{trade_id}",
    response_model=TradeRecord,
    responses={
        404: {"model": ErrorResponse, "description": "Trade not found"}
    },
    summary="Get single trade",
    description="Get details for a specific trade by ID."
)
async def get_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    _auth: bool = Depends(verify_credentials),
) -> TradeRecord:
    """
    Get a single trade by ID.
    """
    try:
        trade = db.query(LiveTrade).filter(LiveTrade.id == trade_id).first()

        if not trade:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

        return TradeRecord(
            id=trade.id,
            symbol=trade.symbol,
            timestamp=trade.timestamp,
            action=trade.action,
            quantity=trade.quantity,
            target_price=float(trade.target_price) if trade.target_price else 0.0,
            fill_price=float(trade.fill_price) if trade.fill_price else None,
            fill_value=float(trade.fill_value) if trade.fill_value else None,
            slippage_pct=float(trade.slippage_pct) if trade.slippage_pct is not None else 0.0,
            schwab_order_id=trade.schwab_order_id,
            strategy_cell=trade.strategy_cell,
            trend_state=trade.trend_state,
            vol_state=trade.vol_state,
            t_norm=float(trade.t_norm) if trade.t_norm else None,
            z_score=float(trade.z_score) if trade.z_score else None,
            reason=trade.reason,
            mode=trade.mode,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trade get error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/summary/stats",
    summary="Get trade statistics",
    description="Get summary statistics for trades."
)
async def get_trade_stats(
    db: Session = Depends(get_db),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    start_date: Optional[datetime] = Query(None, description="Start date"),
    end_date: Optional[datetime] = Query(None, description="End date"),
    _auth: bool = Depends(verify_credentials),
) -> dict:
    """
    Get trade statistics summary.

    Returns:
    - Total trades
    - Buy/sell counts
    - Trade volume
    - Average slippage
    - Win rate (from matched round-trip trades)
    - Net P&L (realized profit/loss)
    """
    try:
        from sqlalchemy import func
        from collections import defaultdict

        query = db.query(LiveTrade)

        filters = []
        if mode:
            filters.append(LiveTrade.mode == mode)
        if start_date:
            filters.append(LiveTrade.timestamp >= start_date)
        if end_date:
            filters.append(LiveTrade.timestamp <= end_date)

        if filters:
            query = query.filter(and_(*filters))

        # Get counts
        total_trades = query.count()
        buy_trades = query.filter(LiveTrade.action == 'BUY').count()
        sell_trades = query.filter(LiveTrade.action == 'SELL').count()

        # Get volume stats
        volume_result = db.query(
            func.sum(LiveTrade.fill_value)
        ).filter(
            and_(*filters) if filters else True
        ).first()

        total_volume = float(volume_result[0]) if volume_result[0] else 0.0

        # Get slippage stats
        slippage_result = db.query(
            func.avg(LiveTrade.slippage_pct),
            func.max(LiveTrade.slippage_pct),
            func.min(LiveTrade.slippage_pct)
        ).filter(
            and_(*filters) if filters else True,
            LiveTrade.slippage_pct.isnot(None)
        ).first()

        avg_slippage = float(slippage_result[0]) if slippage_result[0] else None
        max_slippage = float(slippage_result[1]) if slippage_result[1] else None
        min_slippage = float(slippage_result[2]) if slippage_result[2] else None

        # Get unique symbols
        symbols = db.query(LiveTrade.symbol).filter(
            and_(*filters) if filters else True
        ).distinct().all()

        # Calculate win rate and net P&L from matched round-trip trades
        # Using FIFO matching: BUYs are matched with subsequent SELLs
        win_rate = None
        net_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        total_round_trips = 0

        # Get all trades ordered by timestamp for P&L matching
        all_trades = query.order_by(LiveTrade.timestamp).all()

        # Track open positions by symbol (FIFO queue of BUY trades)
        open_positions = defaultdict(list)  # symbol -> list of (quantity, fill_price, fill_value)

        for trade in all_trades:
            if not trade.fill_price or not trade.quantity:
                continue

            fill_price = float(trade.fill_price)
            quantity = trade.quantity

            if trade.action == 'BUY':
                # Add to open position
                open_positions[trade.symbol].append({
                    'quantity': quantity,
                    'fill_price': fill_price,
                })
            elif trade.action == 'SELL':
                # Match against open BUY positions (FIFO)
                remaining_to_sell = quantity

                while remaining_to_sell > 0 and open_positions[trade.symbol]:
                    buy_trade = open_positions[trade.symbol][0]
                    buy_qty = buy_trade['quantity']
                    buy_price = buy_trade['fill_price']

                    # Determine how much we can close
                    close_qty = min(remaining_to_sell, buy_qty)

                    # Calculate P&L for this portion
                    pnl = (fill_price - buy_price) * close_qty
                    net_pnl += pnl
                    total_round_trips += 1

                    if pnl > 0:
                        winning_trades += 1
                    else:
                        losing_trades += 1

                    # Update remaining quantities
                    remaining_to_sell -= close_qty
                    buy_trade['quantity'] -= close_qty

                    # Remove fully closed position
                    if buy_trade['quantity'] <= 0:
                        open_positions[trade.symbol].pop(0)

        # Calculate win rate as percentage
        if total_round_trips > 0:
            win_rate = winning_trades / total_round_trips

        return {
            "total_trades": total_trades,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "total_volume": total_volume,
            "avg_slippage_pct": avg_slippage,
            "max_slippage_pct": max_slippage,
            "min_slippage_pct": min_slippage,
            "unique_symbols": [s[0] for s in symbols],
            "win_rate": win_rate,
            "net_pnl": round(net_pnl, 2),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_round_trips": total_round_trips,
        }

    except Exception as e:
        logger.error(f"Trade stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/execute",
    response_model=ExecuteTradeResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Execution error"},
    },
    summary="Execute a trade",
    description="Execute a manual trade through Jutsu Trader dashboard."
)
async def execute_trade(
    request: ExecuteTradeRequest,
    db: Session = Depends(get_db),
    _auth = Depends(require_permission("trades:execute")),
) -> ExecuteTradeResponse:
    """
    Execute a trade manually from Jutsu Trader dashboard.

    Workflow:
    1. Validate request (symbol, action, quantity)
    2. Fetch current price for the symbol
    3. Determine trading mode (mock or live)
    4. Execute trade via appropriate executor
    5. Record trade in database
    6. Return execution result

    Args:
        request: Trade execution request with symbol, action, quantity

    Returns:
        ExecuteTradeResponse with execution details
    """
    try:
        # Step 1: Validate symbol
        symbol = request.symbol.upper()
        if symbol not in VALID_SYMBOLS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid symbol: {symbol}. Valid symbols: {', '.join(sorted(VALID_SYMBOLS))}"
            )

        # Step 2: Validate action
        action = request.action.upper()
        if action not in ('BUY', 'SELL'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action: {action}. Must be BUY or SELL"
            )

        quantity = request.quantity
        reason = request.reason or f"Manual {action} via Jutsu Trader"

        logger.info(f"Executing trade: {action} {quantity} {symbol} - {reason}")

        # Step 3: Get current price (try Schwab API, fallback to estimate)
        current_price = await _get_current_price(symbol)
        if current_price is None:
            raise HTTPException(
                status_code=500,
                detail=f"Unable to fetch current price for {symbol}"
            )

        # Step 4: Determine trading mode and execute
        engine_state = get_engine_state()
        mode = engine_state.mode

        # Load config for executor
        config = load_config()

        # Import executor based on mode
        from jutsu_engine.live.mock_order_executor import MockOrderExecutor
        from jutsu_engine.live.mode import TradingMode

        # Create executor (always mock for now, live execution requires more safety checks)
        executor = MockOrderExecutor(
            config=config,
            trade_log_path=Path('logs/live_trades.csv'),
            db_session=db
        )

        # Build position diff for executor
        if action == 'BUY':
            position_diff = {symbol: quantity}
        else:  # SELL
            position_diff = {symbol: -quantity}

        # Execute trade
        fills, fill_prices = executor.execute_rebalance(
            position_diffs=position_diff,
            current_prices={symbol: current_price},
            reason=reason,
            strategy_context={
                'current_cell': None,
                'trend_state': None,
                'vol_state': None,
                't_norm': None,
                'z_score': None
            }
        )

        # Step 5: Check result
        if not fills:
            return ExecuteTradeResponse(
                success=False,
                trade_id=None,
                symbol=symbol,
                action=action,
                quantity=quantity,
                target_price=float(current_price),
                fill_price=None,
                fill_value=None,
                slippage_pct=None,
                message="No fills generated - trade may have been below threshold",
                timestamp=datetime.now(timezone.utc)
            )

        # Get the fill for this trade
        fill = fills[0]

        # Get the trade ID from database (most recent for this symbol)
        trade_record = db.query(LiveTrade).filter(
            LiveTrade.symbol == symbol
        ).order_by(desc(LiveTrade.timestamp)).first()

        trade_id = trade_record.id if trade_record else None

        logger.info(
            f"Trade executed: {action} {quantity} {symbol} @ ${fill['fill_price']:.2f} "
            f"= ${fill['value']:,.2f} (ID: {trade_id})"
        )

        return ExecuteTradeResponse(
            success=True,
            trade_id=trade_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            target_price=float(fill['expected_price']),
            fill_price=float(fill['fill_price']),
            fill_value=float(fill['value']),
            slippage_pct=float(fill['slippage_pct']) if fill.get('slippage_pct') is not None else 0.0,
            message=f"Successfully executed {action} {quantity} {symbol}",
            timestamp=datetime.now(timezone.utc)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trade execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def _get_current_price(symbol: str) -> Optional[Decimal]:
    """
    Fetch current price for a symbol.

    Tries Schwab API first, falls back to database or estimate.

    Args:
        symbol: Stock symbol

    Returns:
        Current price as Decimal, or None if unavailable
    """
    try:
        # Try to get price from Schwab API
        from jutsu_engine.api.dependencies import get_strategy_runner

        try:
            runner = get_strategy_runner()
            # Use the data fetcher if available
            if hasattr(runner, 'data_fetcher') and runner.data_fetcher:
                price = runner.data_fetcher.fetch_current_quote(symbol)
                logger.info(f"Got live price for {symbol}: ${price}")
                return price
        except Exception as e:
            logger.warning(f"Could not get live price for {symbol}: {e}")

        # Fallback: Use recent market data from database
        from jutsu_engine.data.models import MarketData
        from jutsu_engine.api.dependencies import get_db_context

        with get_db_context() as db:
            recent = db.query(MarketData).filter(
                MarketData.symbol == symbol,
                MarketData.timeframe == '1D'
            ).order_by(desc(MarketData.timestamp)).first()

            if recent:
                price = Decimal(str(recent.close))
                logger.info(f"Using database price for {symbol}: ${price}")
                return price

        # Last fallback: Hard-coded estimates (should rarely hit this)
        estimates = {
            'QQQ': Decimal('500.00'),
            'TQQQ': Decimal('75.00'),
            'PSQ': Decimal('10.00'),
            'TMF': Decimal('45.00'),
            'TMV': Decimal('25.00'),
            'TLT': Decimal('90.00'),
        }
        if symbol in estimates:
            logger.warning(f"Using estimated price for {symbol}: ${estimates[symbol]}")
            return estimates[symbol]

        return None

    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return None
