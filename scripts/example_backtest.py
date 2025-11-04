"""
Example backtest script demonstrating Vibe Engine usage.

This script shows how to:
1. Setup the environment
2. Load configuration
3. Run a backtest with a strategy
4. View results

Note: This is a skeleton example. Full implementation requires completing
the MVP phase with EventLoop, PortfolioSimulator, and PerformanceAnalyzer.
"""
from decimal import Decimal
from datetime import datetime

# Import Vibe Engine components
# from jutsu_engine.application.backtest_runner import BacktestRunner
# from jutsu_engine.strategies.sma_crossover import SMA_Crossover
from jutsu_engine.utils.config import get_config
from jutsu_engine.utils.logging_config import setup_logger

# Setup logging
logger = setup_logger('EXAMPLE', log_to_console=True)


def main():
    """Run example backtest."""
    logger.info("=" * 60)
    logger.info("Vibe Engine - Example Backtest")
    logger.info("=" * 60)

    # Load configuration
    config = get_config()
    logger.info(f"Environment: {config.environment}")
    logger.info(f"Database: {config.database_url}")
    logger.info(f"Initial Capital: ${config.initial_capital:,.2f}")

    # Backtest configuration
    backtest_config = {
        'symbol': 'AAPL',
        'timeframe': '1D',
        'start_date': datetime(2024, 1, 1),
        'end_date': datetime(2024, 12, 31),
        'initial_capital': Decimal('100000'),
        'commission_per_share': Decimal('0.01'),
    }

    logger.info("\nBacktest Configuration:")
    for key, value in backtest_config.items():
        logger.info(f"  {key}: {value}")

    # TODO: Once MVP is complete, uncomment this:
    # # Initialize strategy
    # strategy = SMA_Crossover(short_period=20, long_period=50)
    #
    # # Run backtest
    # logger.info("\nRunning backtest...")
    # runner = BacktestRunner(backtest_config)
    # results = runner.run(strategy=strategy)
    #
    # # Display results
    # logger.info("\nBacktest Results:")
    # logger.info(f"  Total Return: {results['total_return']:.2%}")
    # logger.info(f"  Annualized Return: {results['annualized_return']:.2%}")
    # logger.info(f"  Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    # logger.info(f"  Max Drawdown: {results['max_drawdown']:.2%}")
    # logger.info(f"  Total Trades: {results['total_trades']}")
    # logger.info(f"  Win Rate: {results['win_rate']:.2%}")

    logger.info(
        "\nNOTE: This is a skeleton example. Complete MVP implementation to run actual backtests."
    )
    logger.info(
        "Next steps: Implement EventLoop, PortfolioSimulator, and PerformanceAnalyzer."
    )


if __name__ == '__main__':
    main()
