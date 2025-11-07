"""
Optimization result storage and management.

Provides storage, retrieval, and ranking of optimization results.
Supports PostgreSQL persistence for historical result tracking.
"""
from typing import Dict, List, Any, Optional
from decimal import Decimal
from datetime import datetime
import json

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from jutsu_engine.utils.logging_config import setup_logger
from jutsu_engine.utils.config import get_config

logger = setup_logger('APP.OPTIMIZATION.RESULTS')

Base = declarative_base()


class OptimizationResultModel(Base):
    """SQLAlchemy model for optimization results."""

    __tablename__ = 'optimization_results'

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    objective = Column(String(50), nullable=False)
    objective_value = Column(Float, nullable=False, index=True)
    parameters = Column(Text, nullable=False)  # JSON string
    optimizer_type = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    additional_data = Column(Text)  # Additional data as JSON (renamed from metadata to avoid conflict)


class OptimizationResults:
    """
    Manager for optimization result storage and retrieval.

    Stores results in PostgreSQL for historical tracking and comparison.
    Provides filtering, ranking, and retrieval capabilities.

    Example:
        >>> results_manager = OptimizationResults()
        >>>
        >>> # Store results
        >>> results_manager.store(
        ...     strategy_name='SMA_Crossover',
        ...     optimizer_type='grid_search',
        ...     objective='sharpe_ratio',
        ...     objective_value=1.85,
        ...     parameters={'short_period': 20, 'long_period': 50},
        ...     symbol='AAPL',
        ...     timeframe='1D',
        ...     start_date=datetime(2020, 1, 1),
        ...     end_date=datetime(2023, 1, 1)
        ... )
        >>>
        >>> # Retrieve best results
        >>> best = results_manager.get_best(
        ...     strategy_name='SMA_Crossover',
        ...     symbol='AAPL',
        ...     n=10
        ... )
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize results manager.

        Args:
            database_url: Database URL. If None, uses config default.

        Raises:
            Exception: If database connection fails
        """
        if database_url is None:
            config = get_config()
            database_url = config.database_url

        self.engine = create_engine(database_url)
        Base.metadata.create_all(self.engine)

        Session_factory = sessionmaker(bind=self.engine)
        self.session: Session = Session_factory()

        logger.info(f"OptimizationResults connected to database")

    def store(
        self,
        strategy_name: str,
        optimizer_type: str,
        objective: str,
        objective_value: float,
        parameters: Dict[str, Any],
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Store optimization result.

        Args:
            strategy_name: Name of strategy optimized
            optimizer_type: Type of optimizer ('grid_search', 'genetic', etc.)
            objective: Objective function name
            objective_value: Objective function value achieved
            parameters: Parameter dictionary
            symbol: Stock symbol
            timeframe: Data timeframe
            start_date: Backtest start date
            end_date: Backtest end date
            metadata: Additional data to store

        Returns:
            Result ID

        Raises:
            Exception: If database operation fails
        """
        result = OptimizationResultModel(
            strategy_name=strategy_name,
            optimizer_type=optimizer_type,
            objective=objective,
            objective_value=objective_value,
            parameters=json.dumps(parameters),
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            additional_data=json.dumps(metadata) if metadata else None
        )

        self.session.add(result)
        self.session.commit()

        logger.info(
            f"Stored result: {strategy_name} on {symbol}, "
            f"{objective}={objective_value:.4f}, ID={result.id}"
        )

        return result.id

    def get_best(
        self,
        strategy_name: Optional[str] = None,
        symbol: Optional[str] = None,
        objective: Optional[str] = None,
        n: int = 10,
        minimize: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get best optimization results.

        Args:
            strategy_name: Filter by strategy name
            symbol: Filter by symbol
            objective: Filter by objective function
            n: Number of results to return
            minimize: True for minimization objectives (e.g., max_drawdown)

        Returns:
            List of result dictionaries, sorted by objective value
        """
        query = self.session.query(OptimizationResultModel)

        # Apply filters
        if strategy_name:
            query = query.filter(
                OptimizationResultModel.strategy_name == strategy_name
            )

        if symbol:
            query = query.filter(OptimizationResultModel.symbol == symbol)

        if objective:
            query = query.filter(OptimizationResultModel.objective == objective)

        # Sort by objective value
        if minimize:
            query = query.order_by(OptimizationResultModel.objective_value.asc())
        else:
            query = query.order_by(OptimizationResultModel.objective_value.desc())

        # Limit results
        results = query.limit(n).all()

        # Convert to dictionaries
        return [self._model_to_dict(r) for r in results]

    def get_by_id(self, result_id: int) -> Optional[Dict[str, Any]]:
        """
        Get result by ID.

        Args:
            result_id: Result ID

        Returns:
            Result dictionary or None if not found
        """
        result = self.session.query(OptimizationResultModel).filter(
            OptimizationResultModel.id == result_id
        ).first()

        if result:
            return self._model_to_dict(result)
        return None

    def get_history(
        self,
        strategy_name: str,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get optimization history for a strategy-symbol pair.

        Args:
            strategy_name: Strategy name
            symbol: Stock symbol
            limit: Maximum number of results

        Returns:
            List of results sorted by creation date (newest first)
        """
        results = self.session.query(OptimizationResultModel).filter(
            OptimizationResultModel.strategy_name == strategy_name,
            OptimizationResultModel.symbol == symbol
        ).order_by(
            OptimizationResultModel.created_at.desc()
        ).limit(limit).all()

        return [self._model_to_dict(r) for r in results]

    def delete_old_results(self, days: int = 90) -> int:
        """
        Delete results older than specified days.

        Args:
            days: Delete results older than this many days

        Returns:
            Number of results deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        count = self.session.query(OptimizationResultModel).filter(
            OptimizationResultModel.created_at < cutoff_date
        ).delete()

        self.session.commit()

        logger.info(f"Deleted {count} results older than {days} days")

        return count

    def _model_to_dict(self, model: OptimizationResultModel) -> Dict[str, Any]:
        """
        Convert SQLAlchemy model to dictionary.

        Args:
            model: OptimizationResultModel instance

        Returns:
            Dictionary representation
        """
        return {
            'id': model.id,
            'strategy_name': model.strategy_name,
            'optimizer_type': model.optimizer_type,
            'objective': model.objective,
            'objective_value': model.objective_value,
            'parameters': json.loads(model.parameters),
            'symbol': model.symbol,
            'timeframe': model.timeframe,
            'start_date': model.start_date,
            'end_date': model.end_date,
            'created_at': model.created_at,
            'metadata': json.loads(model.additional_data) if model.additional_data else None
        }

    def __del__(self):
        """Cleanup database connection."""
        if hasattr(self, 'session'):
            self.session.close()


# Import timedelta for delete_old_results
from datetime import timedelta
