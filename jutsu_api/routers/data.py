"""Data management endpoints for market data operations.

Provides REST API for data synchronization, retrieval,
and metadata management.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone
from typing import List, Dict, Any
import logging

from jutsu_api.models.schemas import DataSyncRequest, DataResponse
from jutsu_api.dependencies import get_db
from jutsu_engine.application.data_sync import DataSync
from jutsu_engine.data.fetchers.schwab import SchwabDataFetcher
from jutsu_engine.data.models import MarketData, DataMetadata

logger = logging.getLogger("API.DATA")

router = APIRouter()


@router.get("/symbols", response_model=List[str])
async def list_available_symbols(
    db: Session = Depends(get_db)
):
    """
    List all symbols with available data.

    Args:
        db: Database session

    Returns:
        List of unique symbol names

    Example:
        GET /api/v1/data/symbols
        Response: ["AAPL", "MSFT", "GOOGL"]
    """
    try:
        symbols = (
            db.query(MarketData.symbol)
            .distinct()
            .order_by(MarketData.symbol)
            .all()
        )

        symbol_list = [symbol[0] for symbol in symbols]

        logger.info(f"Retrieved {len(symbol_list)} symbols")

        return symbol_list

    except Exception as e:
        logger.error(f"Failed to list symbols: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve symbols: {str(e)}"
        )


@router.post("/sync", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def sync_market_data(
    request: DataSyncRequest,
    db: Session = Depends(get_db)
):
    """
    Trigger data synchronization for a symbol.

    Fetches market data from external source and stores in database.
    Supports incremental updates.

    Args:
        request: Data sync configuration
        db: Database session

    Returns:
        Sync results with statistics

    Raises:
        HTTPException: 400 if validation fails, 500 if sync fails

    Example:
        POST /api/v1/data/sync
        {
            "symbol": "AAPL",
            "source": "schwab",
            "timeframe": "1D",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-12-31T00:00:00"
        }
    """
    try:
        logger.info(
            f"Starting data sync: {request.symbol} {request.timeframe} "
            f"from {request.start_date.date()}"
        )

        # Create data fetcher based on source
        if request.source == "schwab":
            fetcher = SchwabDataFetcher()
        else:
            raise ValueError(f"Unsupported data source: {request.source}")

        # Create data sync instance
        sync = DataSync(session=db)

        # Perform synchronization
        result = sync.sync_symbol(
            fetcher=fetcher,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            force_refresh=request.force_refresh
        )

        logger.info(
            f"Sync completed: {result['bars_stored']} bars stored, "
            f"{result['bars_updated']} updated"
        )

        return {
            'status': 'success',
            'symbol': request.symbol,
            'timeframe': request.timeframe,
            'bars_fetched': result['bars_fetched'],
            'bars_stored': result['bars_stored'],
            'bars_updated': result['bars_updated'],
            'duration_seconds': result['duration_seconds'],
            'date_range': {
                'start': result['start_date'],
                'end': result['end_date']
            }
        }

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Data sync failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Data synchronization failed: {str(e)}"
        )


@router.get("/{symbol}/bars", response_model=List[Dict[str, Any]])
async def get_market_data_bars(
    symbol: str,
    timeframe: str = "1D",
    start_date: datetime = None,
    end_date: datetime = None,
    limit: int = 1000,
    db: Session = Depends(get_db)
):
    """
    Retrieve OHLCV bars for a symbol.

    Args:
        symbol: Stock ticker symbol
        timeframe: Data timeframe (default: "1D")
        start_date: Optional start date filter
        end_date: Optional end date filter
        limit: Maximum number of bars (default: 1000)
        db: Database session

    Returns:
        List of OHLCV bars

    Raises:
        HTTPException: 404 if no data found, 500 on error

    Example:
        GET /api/v1/data/AAPL/bars?timeframe=1D&limit=100
    """
    try:
        query = db.query(MarketData).filter(
            and_(
                MarketData.symbol == symbol,
                MarketData.timeframe == timeframe,
                MarketData.is_valid == True  # noqa: E712
            )
        )

        # Apply date filters if provided
        if start_date:
            query = query.filter(MarketData.timestamp >= start_date)
        if end_date:
            query = query.filter(MarketData.timestamp <= end_date)

        # Order by timestamp and limit
        bars = (
            query
            .order_by(MarketData.timestamp.asc())
            .limit(limit)
            .all()
        )

        if not bars:
            logger.warning(f"No data found for {symbol} {timeframe}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for {symbol} {timeframe}"
            )

        # Convert to dictionaries
        bars_data = [
            {
                'timestamp': bar.timestamp,
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': bar.volume,
                'data_source': bar.data_source
            }
            for bar in bars
        ]

        logger.info(f"Retrieved {len(bars_data)} bars for {symbol} {timeframe}")

        return bars_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve bars: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve market data: {str(e)}"
        )


@router.get("/metadata", response_model=List[Dict[str, Any]])
async def get_data_metadata(
    symbol: str = None,
    db: Session = Depends(get_db)
):
    """
    Get data availability metadata.

    Provides information about available data for symbols,
    including date ranges and bar counts.

    Args:
        symbol: Optional symbol filter
        db: Database session

    Returns:
        List of metadata records

    Example:
        GET /api/v1/data/metadata?symbol=AAPL
    """
    try:
        query = db.query(DataMetadata)

        if symbol:
            query = query.filter(DataMetadata.symbol == symbol)

        metadata_records = query.all()

        # Convert to dictionaries
        metadata_list = [
            {
                'symbol': record.symbol,
                'timeframe': record.timeframe,
                'total_bars': record.total_bars,
                'last_bar_timestamp': record.last_bar_timestamp,
                'last_updated': record.last_updated
            }
            for record in metadata_records
        ]

        logger.info(f"Retrieved {len(metadata_list)} metadata records")

        return metadata_list

    except Exception as e:
        logger.error(f"Failed to retrieve metadata: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve metadata: {str(e)}"
        )


@router.post("/{symbol}/validate", response_model=Dict[str, Any])
async def validate_market_data(
    symbol: str,
    timeframe: str = "1D",
    db: Session = Depends(get_db)
):
    """
    Validate data quality for a symbol.

    Checks for:
    - Invalid OHLC relationships
    - Missing bars (gaps)
    - Zero volume bars
    - Duplicate timestamps

    Args:
        symbol: Stock ticker symbol
        timeframe: Data timeframe (default: "1D")
        db: Database session

    Returns:
        Validation results with issue details

    Example:
        POST /api/v1/data/AAPL/validate?timeframe=1D
    """
    try:
        logger.info(f"Validating data for {symbol} {timeframe}")

        sync = DataSync(session=db)
        validation_result = sync.validate_data(
            symbol=symbol,
            timeframe=timeframe
        )

        logger.info(
            f"Validation complete: {validation_result['valid_bars']}/{validation_result['total_bars']} valid"
        )

        return {
            'status': 'success',
            'symbol': symbol,
            'timeframe': timeframe,
            'total_bars': validation_result['total_bars'],
            'valid_bars': validation_result['valid_bars'],
            'invalid_bars': validation_result['invalid_bars'],
            'issues': validation_result['issues'][:100]  # Limit issues to 100
        }

    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Data validation failed: {str(e)}"
        )
