"""
Adaptive Kalman Filter with Trend Strength Oscillator.

This module implements a stateful Kalman filter for price prediction with trend strength measurement.
Unlike other indicators in this package, this is STATEFUL and must be initialized once per symbol.

Based on TradingView indicator by Zeiierman.

Example:
    from jutsu_engine.indicators.kalman import AdaptiveKalmanFilter, KalmanFilterModel

    # Initialize filter
    kf = AdaptiveKalmanFilter(
        model=KalmanFilterModel.VOLUME_ADJUSTED,
        process_noise_1=0.01,
        measurement_noise=500.0
    )

    # Update bar-by-bar
    for bar in data:
        filtered_price, trend_strength = kf.update(
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume
        )
"""
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Tuple
import numpy as np
import logging

logger = logging.getLogger('INFRA.INDICATORS.KALMAN')


class KalmanFilterModel(Enum):
    """
    Noise adjustment model for Kalman filter.

    Attributes:
        STANDARD: Fixed measurement noise (no adjustment)
        VOLUME_ADJUSTED: Adjusts noise based on volume ratio
        PARKINSON_ADJUSTED: Adjusts noise based on high-low range
    """
    STANDARD = "standard"
    VOLUME_ADJUSTED = "volume_adjusted"
    PARKINSON_ADJUSTED = "parkinson_adjusted"


class AdaptiveKalmanFilter:
    """
    Adaptive Kalman Filter with Trend Strength Oscillator.

    This is a stateful indicator maintaining internal matrices and buffers.
    Must be initialized once and updated bar-by-bar.

    Mathematical Background:
    - State vector X = [position, velocity]
    - Prediction: X_pred = F @ X, P_pred = F @ P @ F.T + Q
    - Update: K = P @ H.T @ inv(S), X = X + K @ innovation
    - Trend strength: WMA(oscillator / max_oscillator * 100)

    Performance:
        <5ms per update (NumPy operations)

    Attributes:
        model: Noise adjustment strategy
        F: 2x2 state transition matrix
        P: 2x2 covariance matrix
        Q: 2x2 process noise matrix
        R: 1x1 measurement noise matrix
        H: 1x2 observation matrix
        I: 2x2 identity matrix
        X: 2x1 state vector [position, velocity]
        innovation_buffer: Circular buffer for innovations
        oscillator_buffer: Circular buffer for oscillators
        smoothed_oscillator_buffer: Buffer for double smoothing intermediate values
        prev_high: Previous bar high price
        prev_low: Previous bar low price
        prev_volume: Previous bar volume
        bar_count: Number of bars processed
        symmetric_volume_adjustment: If True, volume adjustment is bidirectional
        double_smoothing: If True, applies double WMA smoothing
    """

    def __init__(
        self,
        process_noise_1: float = 0.01,
        process_noise_2: float = 0.01,
        measurement_noise: float = 500.0,
        model: KalmanFilterModel = KalmanFilterModel.STANDARD,
        sigma_lookback: int = 500,
        trend_lookback: int = 10,
        osc_smoothness: int = 10,
        strength_smoothness: int = 10,
        return_signed: bool = False,
        symmetric_volume_adjustment: bool = False,
        double_smoothing: bool = False
    ):
        """
        Initialize Adaptive Kalman Filter.

        Args:
            process_noise_1: Process noise for position (default: 0.01)
            process_noise_2: Process noise for velocity (default: 0.01)
            measurement_noise: Base measurement noise (default: 500.0)
            model: Noise adjustment model (default: STANDARD)
            sigma_lookback: Innovation buffer size (default: 500)
            trend_lookback: Oscillator buffer size (default: 10)
            osc_smoothness: Smoothing period for oscillator (default: 10)
            strength_smoothness: Smoothing period for trend strength (default: 10)
            return_signed: Return signed trend_strength (default: False for backward compatibility)
                          If True, returns signed trend_strength in [-100, +100] range
                          If False, returns abs(trend_strength) in [0, 100] range (legacy)
            symmetric_volume_adjustment: Enable symmetric volume-based noise adjustment (default: False)
                          If True, noise INCREASES when volume drops (more skeptical on low-volume days)
                          If False, noise only decreases when volume increases (original behavior)
            double_smoothing: Enable double WMA smoothing for trend strength (default: False)
                          If True, applies two WMA passes: first with osc_smoothness, second with strength_smoothness
                          If False, applies single WMA pass with osc_smoothness (original behavior)

        Raises:
            ValueError: If parameters are invalid
        """
        logger.debug(
            f"Initializing AdaptiveKalmanFilter: model={model.value}, "
            f"process_noise=({process_noise_1}, {process_noise_2}), "
            f"measurement_noise={measurement_noise}"
        )

        # Validate parameters
        if process_noise_1 <= 0 or process_noise_2 <= 0:
            raise ValueError("Process noise must be positive")
        if measurement_noise <= 0:
            raise ValueError("Measurement noise must be positive")
        if sigma_lookback <= 0 or trend_lookback <= 0:
            raise ValueError("Lookback periods must be positive")
        if osc_smoothness <= 0 or strength_smoothness <= 0:
            raise ValueError("Smoothness periods must be positive")

        # Store parameters
        self.model = model
        self.sigma_lookback = sigma_lookback
        self.trend_lookback = trend_lookback
        self.osc_smoothness = min(osc_smoothness, trend_lookback)
        self.strength_smoothness = min(strength_smoothness, sigma_lookback)
        self.return_signed = return_signed
        self.symmetric_volume_adjustment = symmetric_volume_adjustment
        self.double_smoothing = double_smoothing

        # Initialize Kalman filter matrices (NumPy for efficiency)
        self.F = np.array([[1.0, 1.0], [0.0, 1.0]])  # State transition
        self.P = np.array([[1.0, 0.0], [0.0, 1.0]])  # Covariance
        self.Q = np.array([
            [process_noise_1, 0.0],
            [0.0, process_noise_2]
        ])  # Process noise
        self.R = np.array([[measurement_noise]])  # Measurement noise (base)
        self.H = np.array([[1.0, 0.0]])  # Observation matrix
        self.I = np.eye(2)  # Identity

        # Initialize state vector
        self.X = np.array([[0.0], [0.0]])  # [position, velocity]

        # Buffers for trend strength calculation
        self.innovation_buffer: List[float] = []
        self.oscillator_buffer: List[float] = []
        self.smoothed_oscillator_buffer: List[float] = []  # For double smoothing

        # Previous values for noise adjustment
        self.prev_high: Optional[float] = None
        self.prev_low: Optional[float] = None
        self.prev_volume: Optional[float] = None

        # Initialization flag
        self.bar_count = 0

    def update(
        self,
        close: Decimal,
        high: Optional[Decimal] = None,
        low: Optional[Decimal] = None,
        volume: Optional[Decimal] = None
    ) -> Tuple[Decimal, Decimal]:
        """
        Update filter with new bar.

        Args:
            close: Close price (required)
            high: High price (required for Parkinson model)
            low: Low price (required for Parkinson model)
            volume: Volume (required for Volume-adjusted model)

        Returns:
            (filtered_price, trend_strength) as Decimals
            - filtered_price: Kalman-filtered price (always positive)
            - trend_strength: If return_signed=True, signed trend strength in [-100, +100]
                            If return_signed=False, absolute trend strength in [0, 100]

        Raises:
            ValueError: If required parameters for model are missing
        """
        # Convert Decimal to float for NumPy
        close_f = float(close)
        high_f = float(high) if high is not None else None
        low_f = float(low) if low is not None else None
        volume_f = float(volume) if volume is not None else None

        logger.debug(
            f"Update bar {self.bar_count}: close={close_f}, "
            f"model={self.model.value}"
        )

        # Validate required inputs for model
        if self.model == KalmanFilterModel.PARKINSON_ADJUSTED:
            if high_f is None or low_f is None:
                raise ValueError("Parkinson model requires high and low prices")
        if self.model == KalmanFilterModel.VOLUME_ADJUSTED:
            if volume_f is None:
                raise ValueError("Volume-adjusted model requires volume")

        # Initialize state on first bar
        if self.bar_count == 0:
            self.X[0, 0] = close_f
            self.prev_high = high_f
            self.prev_low = low_f
            self.prev_volume = volume_f
            self.bar_count += 1
            logger.debug(f"Initialized state: X={self.X.flatten()}")
            return close, Decimal('0.0')

        # ===== PREDICTION STEP =====
        # X_pred = F @ X
        X_pred = self.F @ self.X

        # P_pred = F @ P @ F.T + Q
        P_pred = self.F @ self.P @ self.F.T + self.Q

        # ===== MEASUREMENT NOISE ADJUSTMENT =====
        R_adjusted = self._adjust_measurement_noise(
            close_f, high_f, low_f, volume_f
        )

        # ===== UPDATE STEP =====
        # Innovation covariance: S = H @ P_pred @ H.T + R
        S = self.H @ P_pred @ self.H.T + R_adjusted

        # Kalman gain: K = P_pred @ H.T @ inv(S)
        K = P_pred @ self.H.T @ np.linalg.inv(S)

        # Innovation (measurement residual): y = z - H @ X_pred
        z = np.array([[close_f]])
        innovation = z - self.H @ X_pred

        # Update state: X = X_pred + K @ innovation
        self.X = X_pred + K @ innovation

        # Update covariance: P = (I - K @ H) @ P_pred
        self.P = (self.I - K @ self.H) @ P_pred

        # ===== TREND STRENGTH CALCULATION =====
        trend_strength = self._calculate_trend_strength(innovation[0, 0])

        # Update previous values for next iteration
        self.prev_high = high_f
        self.prev_low = low_f
        self.prev_volume = volume_f
        self.bar_count += 1

        # Convert back to Decimal
        filtered_price = Decimal(str(self.X[0, 0]))
        trend_strength_decimal = Decimal(str(trend_strength))

        logger.debug(
            f"State updated: X={self.X.flatten()}, "
            f"filtered={filtered_price}, strength={trend_strength_decimal}"
        )

        return filtered_price, trend_strength_decimal

    def _adjust_measurement_noise(
        self,
        close: float,
        high: Optional[float],
        low: Optional[float],
        volume: Optional[float]
    ) -> np.ndarray:
        """
        Adjust measurement noise based on selected model.

        Args:
            close: Current close price
            high: Current high price
            low: Current low price
            volume: Current volume

        Returns:
            Adjusted measurement noise matrix (1x1)
        """
        R_base = self.R.copy()

        if self.model == KalmanFilterModel.STANDARD:
            return R_base

        elif self.model == KalmanFilterModel.VOLUME_ADJUSTED:
            # Adjust based on volume ratio
            if self.prev_volume is not None and volume is not None:
                if volume > 0:
                    if self.symmetric_volume_adjustment:
                        # Symmetric: noise INCREASES when volume drops, DECREASES when volume rises
                        # Volume 100→50: ratio=2.0 (more skeptical on low-volume days)
                        # Volume 100→200: ratio=0.5 (more confident on high-volume days)
                        vol_ratio = self.prev_volume / volume
                    else:
                        # Original: noise only decreases when volume increases
                        # Volume 100→50: ratio=1.0 (baseline, no change)
                        # Volume 100→200: ratio=0.5 (more confident)
                        vol_ratio = self.prev_volume / max(self.prev_volume, volume)
                    R_adjusted = R_base * vol_ratio
                    logger.debug(f"Volume adjustment: ratio={vol_ratio:.4f}, symmetric={self.symmetric_volume_adjustment}")
                    return R_adjusted
            return R_base

        elif self.model == KalmanFilterModel.PARKINSON_ADJUSTED:
            # Adjust based on high-low range ratio
            if (self.prev_high is not None and self.prev_low is not None and
                high is not None and low is not None):

                prev_range = max(self.prev_high - self.prev_low, 1e-6)
                curr_range = max(high - low, 1e-6)

                # Higher range = higher noise (less confidence)
                range_ratio = 1.0 + (curr_range / prev_range)
                R_adjusted = R_base * range_ratio
                logger.debug(f"Parkinson adjustment: ratio={range_ratio:.4f}")
                return R_adjusted
            return R_base

        return R_base

    def _calculate_trend_strength(self, innovation: float) -> float:
        """
        Calculate trend strength oscillator using WMA.

        Args:
            innovation: Current innovation (measurement residual)

        Returns:
            Trend strength (0-100 scale)
        """
        # Add innovation to buffer (limited size)
        self.innovation_buffer.append(abs(innovation))
        if len(self.innovation_buffer) > self.sigma_lookback:
            self.innovation_buffer.pop(0)

        # Calculate oscillator if we have enough data
        if len(self.innovation_buffer) >= self.strength_smoothness:
            # Max innovation over lookback
            max_innovation = max(self.innovation_buffer[-self.sigma_lookback:])

            if max_innovation > 0:
                # Normalized oscillator
                oscillator = (innovation / max_innovation) * 100.0
            else:
                oscillator = 0.0

            # Add to oscillator buffer
            self.oscillator_buffer.append(oscillator)
            if len(self.oscillator_buffer) > self.trend_lookback:
                self.oscillator_buffer.pop(0)

            # Calculate WMA of oscillator (first smoothing pass)
            if len(self.oscillator_buffer) >= self.osc_smoothness:
                first_smoothed = self._wma(
                    self.oscillator_buffer,
                    self.osc_smoothness
                )
                
                if self.double_smoothing:
                    # Double smoothing: apply second WMA pass using strength_smoothness
                    self.smoothed_oscillator_buffer.append(first_smoothed)
                    if len(self.smoothed_oscillator_buffer) > self.trend_lookback:
                        self.smoothed_oscillator_buffer.pop(0)
                    
                    if len(self.smoothed_oscillator_buffer) >= self.strength_smoothness:
                        # Second WMA pass
                        trend_strength = self._wma(
                            self.smoothed_oscillator_buffer,
                            self.strength_smoothness
                        )
                    else:
                        # Not enough data for second pass yet, use first pass result
                        trend_strength = first_smoothed
                else:
                    # Original single smoothing behavior
                    trend_strength = first_smoothed
                
                # Return signed or unsigned based on configuration
                if self.return_signed:
                    return trend_strength  # Preserve sign for directional strategies
                else:
                    return abs(trend_strength)  # Legacy behavior (magnitude only)

        return 0.0

    def _wma(self, values: List[float], period: int) -> float:
        """
        Calculate Weighted Moving Average.

        Args:
            values: List of values
            period: Period for WMA

        Returns:
            WMA value
        """
        if len(values) < period:
            return 0.0

        # Weights: 1, 2, 3, ..., period
        weights = np.arange(1, period + 1, dtype=float)
        recent_values = values[-period:]

        return np.dot(recent_values, weights) / weights.sum()

    def reset(self):
        """
        Reset filter state.

        Useful for testing or switching symbols.
        """
        logger.debug("Resetting filter state")

        self.X = np.array([[0.0], [0.0]])
        self.P = np.array([[1.0, 0.0], [0.0, 1.0]])
        self.innovation_buffer.clear()
        self.oscillator_buffer.clear()
        self.smoothed_oscillator_buffer.clear()  # Clear double smoothing buffer
        self.prev_high = None
        self.prev_low = None
        self.prev_volume = None
        self.bar_count = 0
