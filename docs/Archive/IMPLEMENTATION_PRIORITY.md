# Jutsu Labs - Implementation Priority (REVISED)

> Focused roadmap based on actual user priorities: test strategies via CLI and analyze results

**Version:** 2.0
**Last Updated:** November 2, 2025
**Status:** Phase 1 Complete ✅ | Immediate Priorities 🎯

---

## Current Status ✅

**What You Already Have (Phase 1 MVP):**
- ✅ **CLI Commands**: `jutsu init`, `sync`, `status`, `backtest`
- ✅ **Core Engine**: EventLoop, Portfolio, Strategy framework
- ✅ **Data Management**: Schwab API integration, SQLite storage
- ✅ **Strategy Example**: SMA_Crossover (working reference)
- ✅ **Performance Metrics**: 11 metrics including Sharpe, drawdown, win rate
- ✅ **Test Coverage**: 80%+ with comprehensive tests

**What This Means:**
You can ALREADY run backtests on strategies using the CLI! 🎉

---

## Immediate Priorities (Next 4-8 Weeks)

### Priority 1: More Trading Strategies 📈
**Why:** Test different approaches and compare performance
**Time:** 1-2 weeks
**Complexity:** Low-Medium

#### Strategies to Implement:
1. **RSI Strategy** (Mean Reversion)
   - Buy when RSI < 30 (oversold)
   - Sell when RSI > 70 (overbought)
   - Time: 2-3 days

2. **MACD Crossover** (Momentum)
   - Buy when MACD crosses above signal line
   - Sell when MACD crosses below signal line
   - Time: 2-3 days

3. **Bollinger Bands** (Volatility)
   - Buy when price touches lower band
   - Sell when price touches upper band
   - Time: 2-3 days

4. **Multi-Indicator Combo** (Advanced)
   - Combine SMA + RSI + Volume for confirmation
   - More robust signals
   - Time: 4-5 days

#### Implementation:
```python
# jutsu_engine/strategies/rsi_strategy.py
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import rsi

class RSI_Strategy(Strategy):
    def __init__(self, rsi_period=14, oversold=30, overbought=70):
        super().__init__(name="RSI")
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def init(self):
        pass

    def on_bar(self, bar):
        if len(self._bars) < self.rsi_period:
            return

        closes = self.get_closes(lookback=self.rsi_period)
        rsi_value = rsi(closes, self.rsi_period).iloc[-1]

        # Mean reversion logic
        if rsi_value < self.oversold and not self.has_position(bar.symbol):
            self.buy(bar.symbol, 100)
        elif rsi_value > self.overbought and self.has_position(bar.symbol):
            self.sell(bar.symbol, 100)
```

#### CLI Usage:
```bash
# Test RSI strategy
jutsu backtest AAPL \
  --strategy RSI_Strategy \
  --start-date 2023-01-01 \
  --end-date 2024-12-31 \
  --capital 100000

# Compare multiple strategies
jutsu backtest AAPL --strategy SMA_Crossover > sma_results.json
jutsu backtest AAPL --strategy RSI_Strategy > rsi_results.json
jutsu backtest AAPL --strategy MACD_Crossover > macd_results.json
```

---

### Priority 2: Better Results Visualization 📊
**Why:** Easier to analyze and compare strategy performance
**Time:** 1 week
**Complexity:** Low

#### What to Add:
1. **Rich Console Output** (Week 1)
   - Colored terminal output with `rich` library
   - Performance summary table
   - Trade log summary
   - Visual indicators for good/bad metrics

2. **CSV Export** (Week 1)
   - Export detailed results to CSV
   - Easy to analyze in Excel/Google Sheets
   - Trade-by-trade breakdown

3. **Simple Charts** (Week 1)
   - Equity curve visualization
   - Drawdown chart
   - Using `matplotlib` (no web UI needed)
   - Save as PNG files

#### Implementation:
```python
# jutsu_engine/performance/visualizer.py
from rich.console import Console
from rich.table import Table
import matplotlib.pyplot as plt

class ResultsVisualizer:
    def print_summary(self, results: dict):
        """Print colored performance summary"""
        console = Console()

        table = Table(title="📊 Backtest Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")

        # Color code based on thresholds
        sharpe = results['sharpe_ratio']
        sharpe_color = "green" if sharpe > 1.0 else "red"

        table.add_row("Total Return", f"{results['total_return']:.2%}")
        table.add_row("Sharpe Ratio", f"[{sharpe_color}]{sharpe:.2f}[/]")
        table.add_row("Max Drawdown", f"{results['max_drawdown']:.2%}")
        table.add_row("Win Rate", f"{results['win_rate']:.2%}")

        console.print(table)

    def plot_equity_curve(self, equity_series, save_path="equity_curve.png"):
        """Generate equity curve chart"""
        plt.figure(figsize=(12, 6))
        plt.plot(equity_series.index, equity_series.values)
        plt.title("Portfolio Equity Curve")
        plt.xlabel("Date")
        plt.ylabel("Portfolio Value ($)")
        plt.grid(True)
        plt.savefig(save_path)
        print(f"✅ Chart saved: {save_path}")
```

#### CLI Enhancement:
```bash
# Generate visual report
jutsu backtest AAPL --strategy RSI_Strategy --visualize

# Export to CSV
jutsu backtest AAPL --strategy RSI_Strategy --export results.csv

# Save charts
jutsu backtest AAPL --strategy RSI_Strategy --charts output/
```

---

### Priority 3: Strategy Comparison Tool 🔬
**Why:** Easily compare multiple strategies on same data
**Time:** 3-4 days
**Complexity:** Low

#### Features:
```bash
# Compare multiple strategies in one command
jutsu compare AAPL \
  --strategies SMA_Crossover,RSI_Strategy,MACD_Crossover \
  --start-date 2023-01-01 \
  --end-date 2024-12-31

# Output: Side-by-side comparison table
┌─────────────────┬─────────────┬─────────────┬────────────────┐
│ Strategy        │ Total Return│ Sharpe Ratio│ Max Drawdown   │
├─────────────────┼─────────────┼─────────────┼────────────────┤
│ SMA_Crossover   │ +12.5%      │ 1.23        │ -8.2%          │
│ RSI_Strategy    │ +18.3%      │ 1.45        │ -6.5%          │
│ MACD_Crossover  │ +9.7%       │ 0.98        │ -11.2%         │
└─────────────────┴─────────────┴─────────────┴────────────────┘

Best Strategy: RSI_Strategy (Highest Sharpe Ratio)
```

---

### Priority 4: Portfolio-Level Backtesting 💼
**Why:** Test strategies on multiple stocks simultaneously
**Time:** 1-2 weeks
**Complexity:** Medium

#### Features:
```bash
# Test strategy on portfolio of stocks
jutsu backtest-portfolio \
  --symbols AAPL,GOOGL,MSFT,TSLA \
  --strategy RSI_Strategy \
  --allocation equal \
  --start-date 2023-01-01

# Output: Portfolio-level metrics
Portfolio Statistics:
  Total Return: +24.5%
  Sharpe Ratio: 1.67
  Correlation Matrix: [shows diversification]
  Best Performer: GOOGL (+31.2%)
  Worst Performer: TSLA (-5.3%)
```

#### Implementation:
- Extend EventLoop to handle multiple symbols
- Add portfolio-level position management
- Calculate correlation and diversification metrics
- Report individual + combined performance

---

## What NOT to Build Yet ❌

### FastAPI / REST API
**Why Skip:** You don't need programmatic access yet
**When:** Only when you want to:
- Integrate with external tools
- Build a web UI (Phase 3)
- Allow remote execution
- Share backtesting as a service

### Web Dashboard
**Why Skip:** CLI + charts (matplotlib) are sufficient
**When:** Only when you need:
- Interactive exploration
- Real-time monitoring
- Multi-user access
- Professional client demos

### Parameter Optimization
**Why Skip:** First understand strategies manually
**When:** After you've run 10+ backtests manually and want to:
- Find optimal parameters automatically
- Test thousands of combinations
- Walk-forward analysis

### PostgreSQL Migration
**Why Skip:** SQLite works fine for development
**When:** Only when you have:
- >10GB of market data
- Multiple users accessing simultaneously
- Production deployment needs

---

## Revised Implementation Order 🎯

### Phase 2A: Core Enhancements (4-6 weeks) ← YOU ARE HERE
1. **Week 1-2**: More trading strategies (RSI, MACD, Bollinger Bands)
2. **Week 3**: Results visualization (rich output, charts, CSV export)
3. **Week 4**: Strategy comparison tool
4. **Week 5-6**: Portfolio-level backtesting

**Outcome:**
- 4-5 working strategies to test
- Easy comparison and analysis
- Portfolio-level insights
- Everything via CLI (no web needed)

### Phase 2B: Scale & Optimize (4-6 weeks)
1. **Week 7-8**: Multiple data sources (CSV, Yahoo Finance)
2. **Week 9-10**: Parameter optimization framework
3. **Week 11-12**: Advanced metrics and analysis

**Outcome:**
- More data flexibility
- Automated parameter tuning
- Deeper performance insights

### Phase 2C: Service Layer (Optional, 4-6 weeks)
**Only if you need programmatic access**
1. REST API with FastAPI
2. Job queue for long-running backtests
3. API documentation and client libraries

### Phase 3: UI & Distribution (8-10 weeks)
**Only after Phase 2A/2B complete**
1. Web dashboard (Streamlit)
2. Docker deployment
3. Scheduled jobs
4. Monte Carlo simulation

---

## What You Can Do Right Now 🚀

### Immediate Actions (This Week):

#### 1. Test Existing System
```bash
# Sync some data
jutsu sync AAPL --timeframe 1D --start-date 2023-01-01

# Run existing SMA strategy
jutsu backtest AAPL \
  --strategy SMA_Crossover \
  --start-date 2023-01-01 \
  --end-date 2024-10-31 \
  --capital 100000

# Review results
cat results/backtest_AAPL_*.json | python -m json.tool
```

#### 2. Implement First New Strategy (RSI)
```bash
# Use orchestrate to implement RSI strategy
/orchestrate implement strategy RSI with tests and documentation
```

#### 3. Add Results Visualization
```bash
# Enhance CLI output with rich library
/orchestrate add visualization to CLI results with charts
```

---

## Summary: What Changed 🔄

**OLD Priority (Wrong):**
1. ❌ FastAPI REST API ← Not needed yet
2. Parameter Optimization ← Too early
3. PostgreSQL Migration ← Overkill for now
4. Multiple Data Sources ← Can add later
5. Advanced Metrics ← Existing metrics are good

**NEW Priority (Right):**
1. ✅ More Trading Strategies ← Test different approaches
2. ✅ Better Visualization ← Easier analysis
3. ✅ Strategy Comparison ← See what works best
4. ✅ Portfolio Backtesting ← Multiple stocks
5. ✅ Multiple Data Sources ← More flexibility

**Key Insight:**
You already have a working CLI backtesting system! Focus on **using it** to test strategies and analyze results, not building infrastructure you don't need yet.

---

## Next Steps 🎯

**Choose your path:**

**Option A: Test Existing System First** (Recommended)
```bash
# 1. Sync data for a few stocks
jutsu sync AAPL GOOGL MSFT

# 2. Run existing SMA strategy
jutsu backtest AAPL --strategy SMA_Crossover

# 3. Review results and identify what you need
```

**Option B: Add More Strategies Immediately**
```bash
/orchestrate implement RSI strategy with tests
```

**Option C: Improve Results Display**
```bash
/orchestrate enhance CLI output with rich tables and matplotlib charts
```

**Which priority interests you most?**
1. More strategies to test? (RSI, MACD, Bollinger Bands)
2. Better results visualization? (Charts, tables, CSV export)
3. Strategy comparison tool? (Side-by-side performance)
4. Portfolio backtesting? (Multiple stocks at once)

Let me know and I'll implement it right away! 🚀
