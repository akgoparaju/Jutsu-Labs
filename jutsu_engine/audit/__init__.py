"""Read-only analysis layer for the baseline audit / Gauntlet v1.

This package adds ONLY analysis on top of existing infrastructure
(BacktestRunner, PerformanceAnalyzer, LiveStrategyRunner). It never
mutates the database and never touches live/scheduler code paths.
Outputs are files under claudedocs/audit/<YYYY-MM-DD>/.
"""
