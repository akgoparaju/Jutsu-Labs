"""
PostgreSQL bulk operation utilities for high-performance data operations.

Provides COPY-based bulk inserts that are 10-100x faster than individual
INSERT statements.

Example:
    from jutsu_engine.data.bulk_operations import bulk_insert_market_data

    # Bulk insert 10,000 bars in ~500ms
    bulk_insert_market_data(bars, engine)
"""
from io import StringIO
from typing import List
from sqlalchemy.engine import Engine
from jutsu_engine.core.events import MarketDataEvent
from jutsu_engine.utils.logging_config import get_data_logger

logger = get_data_logger('DATABASE.BULK')


def bulk_insert_market_data(
    bars: List[MarketDataEvent],
    engine: Engine,
    chunk_size: int = 10000
) -> int:
    """
    Bulk insert market data bars using PostgreSQL COPY.

    10-100x faster than individual INSERT statements.
    Falls back to SQLAlchemy for SQLite.

    Args:
        bars: List of MarketDataEvent objects to insert
        engine: SQLAlchemy engine
        chunk_size: Number of bars to insert per batch

    Returns:
        Number of bars successfully inserted

    Raises:
        ValueError: If bars list is empty
        DatabaseError: If bulk insert fails

    Example:
        from jutsu_engine.data.bulk_operations import bulk_insert_market_data
        from jutsu_engine.data.database_factory import DatabaseFactory

        engine = DatabaseFactory.create_engine('postgresql', {...})
        inserted = bulk_insert_market_data(bars, engine)
        print(f"Inserted {inserted} bars")
    """
    if not bars:
        raise ValueError("Cannot bulk insert empty list of bars")

    total_inserted = 0

    # Check if PostgreSQL
    if engine.dialect.name == 'postgresql':
        # Use COPY for PostgreSQL (10-100x faster)
        total_inserted = _bulk_insert_postgresql(bars, engine, chunk_size)
    else:
        # Fallback to SQLAlchemy for SQLite
        total_inserted = _bulk_insert_sqlalchemy(bars, engine)

    logger.info(f"Bulk inserted {total_inserted} market data bars")
    return total_inserted


def _bulk_insert_postgresql(
    bars: List[MarketDataEvent],
    engine: Engine,
    chunk_size: int
) -> int:
    """
    PostgreSQL COPY-based bulk insert.

    Args:
        bars: MarketDataEvent objects
        engine: PostgreSQL engine
        chunk_size: Batch size

    Returns:
        Number of rows inserted
    """
    import psycopg2

    total_inserted = 0

    # Process in chunks to manage memory
    for i in range(0, len(bars), chunk_size):
        chunk = bars[i:i + chunk_size]

        # Create CSV buffer
        buffer = StringIO()
        for bar in chunk:
            # Format: symbol, timestamp, timeframe, open, high, low, close, volume, source, is_valid
            buffer.write(
                f"{bar.symbol}\t{bar.timestamp}\t{bar.timeframe}\t"
                f"{bar.open}\t{bar.high}\t{bar.low}\t{bar.close}\t"
                f"{bar.volume}\t{getattr(bar, 'source', 'unknown')}\t"
                f"{getattr(bar, 'is_valid', True)}\n"
            )

        buffer.seek(0)

        # Get raw psycopg2 connection
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()

            # PostgreSQL COPY command
            cursor.copy_from(
                buffer,
                'market_data',
                columns=[
                    'symbol', 'timestamp', 'timeframe',
                    'open', 'high', 'low', 'close', 'volume',
                    'source', 'is_valid'
                ],
                sep='\t'
            )

            raw_conn.commit()
            total_inserted += len(chunk)

            logger.debug(f"Inserted chunk {i // chunk_size + 1}: {len(chunk)} bars")

        except psycopg2.Error as e:
            raw_conn.rollback()
            logger.error(f"PostgreSQL COPY failed: {e}")
            raise
        finally:
            raw_conn.close()

    return total_inserted


def _bulk_insert_sqlalchemy(
    bars: List[MarketDataEvent],
    engine: Engine
) -> int:
    """
    SQLAlchemy-based bulk insert fallback for SQLite.

    Args:
        bars: MarketDataEvent objects
        engine: SQLAlchemy engine

    Returns:
        Number of rows inserted
    """
    from sqlalchemy.orm import sessionmaker
    from jutsu_engine.data.models import MarketData

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Convert events to database models
        db_bars = [
            MarketData(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                timeframe=bar.timeframe,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=getattr(bar, 'source', 'unknown'),
                is_valid=getattr(bar, 'is_valid', True)
            )
            for bar in bars
        ]

        # Bulk insert
        session.bulk_save_objects(db_bars)
        session.commit()

        logger.debug(f"SQLAlchemy bulk insert: {len(bars)} bars")
        return len(bars)

    except Exception as e:
        session.rollback()
        logger.error(f"SQLAlchemy bulk insert failed: {e}")
        raise
    finally:
        session.close()


def bulk_delete_market_data(
    engine: Engine,
    symbol: str = None,
    start_date = None,
    end_date = None
) -> int:
    """
    Bulk delete market data with optional filters.

    Args:
        engine: SQLAlchemy engine
        symbol: Optional symbol filter
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        Number of rows deleted

    Example:
        # Delete all AAPL data
        deleted = bulk_delete_market_data(engine, symbol='AAPL')

        # Delete date range
        deleted = bulk_delete_market_data(
            engine,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2021, 1, 1)
        )
    """
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import and_
    from jutsu_engine.data.models import MarketData

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        query = session.query(MarketData)

        # Apply filters
        filters = []
        if symbol:
            filters.append(MarketData.symbol == symbol)
        if start_date:
            filters.append(MarketData.timestamp >= start_date)
        if end_date:
            filters.append(MarketData.timestamp <= end_date)

        if filters:
            query = query.filter(and_(*filters))

        # Count before delete
        count = query.count()

        # Delete
        query.delete(synchronize_session=False)
        session.commit()

        logger.info(f"Bulk deleted {count} market data rows")
        return count

    except Exception as e:
        session.rollback()
        logger.error(f"Bulk delete failed: {e}")
        raise
    finally:
        session.close()
