from decimal import Decimal
from typing import Optional
from jutsu_engine.core.strategy_base import Strategy
from jutsu_engine.indicators.technical import sma

class QQQ_MA_Crossover(Strategy):
  """
  MA Crossover strategy with long/short capability.

  Long when: 50 MA > 200 MA AND price > 50 MA
  Short when: 50 MA < 200 MA
  Exit on MA crossovers and price breaks.
  """

  def __init__(
      self,
      short_period: int = 50,
      long_period: int = 250,
      position_size_percent: Decimal = Decimal('0.25')  # 25% of portfolio
  ):
      super().__init__()
      self.short_period = short_period
      self.long_period = long_period
      self.position_size_percent = position_size_percent

      # Track previous MA values for crossover detection
      self.prev_short_ma: Optional[Decimal] = None
      self.prev_long_ma: Optional[Decimal] = None

  def init(self):
      """Initialize strategy (called before backtest starts)"""
      self.prev_short_ma = None
      self.prev_long_ma = None

  def on_bar(self, bar):
      """Process each bar and generate signals"""
      symbol = bar.symbol

      # Need enough bars for indicators
      if len(self._bars) < self.long_period:
          return

      # Get historical closes
      closes = self.get_closes(lookback=self.long_period)

      # Calculate moving averages
      short_ma_series = sma(closes, period=self.short_period)
      long_ma_series = sma(closes, period=self.long_period)

      short_ma = short_ma_series.iloc[-1]
      long_ma = long_ma_series.iloc[-1]
      current_price = bar.close

      # Get current position
      current_position = self._positions.get(symbol, 0)

      # === LONG LOGIC ===
      # Long entry: 50 MA > 200 MA AND price > 50 MA
      if short_ma > long_ma and current_price > short_ma:
          # NEW API: Specify portfolio allocation %
          # Portfolio module handles position sizing (cash, margin, commissions)
          self.buy(symbol, self.position_size_percent)
          if current_position == 0:
              self.log(f"LONG ENTRY: 50MA({short_ma:.2f}) > 200MA({long_ma:.2f}), Price({current_price:.2f}) > 50MA")
          elif current_position < 0:
              self.log(f"SHORT EXIT + LONG ENTRY: Reversing position")

      # Long exit: Price breaks below 50 MA
      elif current_position > 0 and current_price < short_ma:
          # Close position by selling with 0% allocation
          self.sell(symbol, Decimal('0.0'))
          self.log(f"LONG EXIT: Price({current_price:.2f}) < 50MA({short_ma:.2f})")

      # === SHORT LOGIC ===
      # Short entry: 50 MA < 200 MA
      if short_ma < long_ma:
          # NEW API: Specify portfolio allocation %
          # Portfolio module handles short margin requirements (150%)
          self.sell(symbol, self.position_size_percent)
          if current_position == 0:
              self.log(f"SHORT ENTRY: 50MA({short_ma:.2f}) < 200MA({long_ma:.2f})")
          elif current_position > 0:
              self.log(f"LONG EXIT + SHORT ENTRY: 50MA crossed below 200MA")

      # Short exit: 50 MA crosses back above 200 MA
      if self.prev_short_ma is not None and self.prev_long_ma is not None:
          # Detect crossover: previous 50MA < 200MA, now 50MA > 200MA
          if self.prev_short_ma < self.prev_long_ma and short_ma > long_ma:
              if current_position < 0:
                  # Cover short by buying with 0% allocation
                  self.buy(symbol, Decimal('0.0'))
                  self.log(f"SHORT EXIT: 50MA crossed above 200MA (crossover)")

      # Store current MA values for next bar
      self.prev_short_ma = short_ma
      self.prev_long_ma = long_ma
