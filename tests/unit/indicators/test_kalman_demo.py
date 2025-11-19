"""
Demonstration of Adaptive Kalman Filter usage.

This is not a test file but a demonstration showing how to use
the Kalman filter in a strategy context.
"""
from decimal import Decimal
import numpy as np

from jutsu_engine.indicators.kalman import (
    AdaptiveKalmanFilter,
    KalmanFilterModel
)


def demo_basic_usage():
    """Demonstrate basic Kalman filter usage."""
    print("\n=== Basic Kalman Filter Demo ===\n")

    # Initialize filter with standard model
    kf = AdaptiveKalmanFilter(
        process_noise_1=0.01,
        process_noise_2=0.01,
        measurement_noise=500.0,
        model=KalmanFilterModel.STANDARD
    )

    # Simulate price data with trend and noise
    np.random.seed(42)
    base_price = 100.0
    prices = []

    for i in range(20):
        # Uptrend with noise
        price = base_price + i * 0.5 + np.random.randn() * 0.3
        prices.append(Decimal(str(round(price, 2))))

    # Update filter bar-by-bar
    print(f"{'Bar':<6} {'Price':<10} {'Filtered':<10} {'Trend%':<10}")
    print("-" * 40)

    for i, price in enumerate(prices):
        filtered, trend_strength = kf.update(close=price)

        print(f"{i:<6} {float(price):<10.2f} {float(filtered):<10.2f} "
              f"{float(trend_strength):<10.2f}")

    print("\nFilter smoothed the noisy prices while tracking the trend.")


def demo_volume_adjusted():
    """Demonstrate volume-adjusted model."""
    print("\n=== Volume-Adjusted Kalman Filter Demo ===\n")

    # Initialize with volume-adjusted model
    kf = AdaptiveKalmanFilter(
        model=KalmanFilterModel.VOLUME_ADJUSTED,
        measurement_noise=500.0
    )

    # Simulate price and volume data
    np.random.seed(42)
    base_price = 100.0
    base_volume = 1000000

    print(f"{'Bar':<6} {'Price':<10} {'Volume':<12} {'Filtered':<10} {'Trend%':<10}")
    print("-" * 60)

    for i in range(15):
        # Price with trend
        price = Decimal(str(round(base_price + i * 0.5 + np.random.randn() * 0.2, 2)))

        # Volume varies (high volume = more confidence)
        volume = Decimal(str(int(base_volume * (0.8 + np.random.rand() * 0.4))))

        filtered, trend_strength = kf.update(
            close=price,
            volume=volume
        )

        print(f"{i:<6} {float(price):<10.2f} {int(volume):<12} "
              f"{float(filtered):<10.2f} {float(trend_strength):<10.2f}")

    print("\nHigh volume bars are trusted more (lower measurement noise).")


def demo_parkinson_adjusted():
    """Demonstrate Parkinson volatility-adjusted model."""
    print("\n=== Parkinson-Adjusted Kalman Filter Demo ===\n")

    # Initialize with Parkinson model
    kf = AdaptiveKalmanFilter(
        model=KalmanFilterModel.PARKINSON_ADJUSTED,
        measurement_noise=500.0
    )

    # Simulate OHLC data
    np.random.seed(42)
    base_price = 100.0

    print(f"{'Bar':<6} {'Close':<10} {'Range':<10} {'Filtered':<10} {'Trend%':<10}")
    print("-" * 60)

    for i in range(15):
        # Price with trend
        close = base_price + i * 0.5 + np.random.randn() * 0.2

        # Varying volatility (range)
        range_size = 0.5 + np.random.rand() * 1.5
        high = Decimal(str(round(close + range_size, 2)))
        low = Decimal(str(round(close - range_size, 2)))
        close_d = Decimal(str(round(close, 2)))

        filtered, trend_strength = kf.update(
            close=close_d,
            high=high,
            low=low
        )

        print(f"{i:<6} {float(close_d):<10.2f} {float(high - low):<10.2f} "
              f"{float(filtered):<10.2f} {float(trend_strength):<10.2f}")

    print("\nWide ranges reduce confidence (higher measurement noise).")


def demo_model_comparison():
    """Compare all three models on the same data."""
    print("\n=== Model Comparison Demo ===\n")

    # Create three filters
    kf_standard = AdaptiveKalmanFilter(
        model=KalmanFilterModel.STANDARD,
        measurement_noise=500.0
    )

    kf_volume = AdaptiveKalmanFilter(
        model=KalmanFilterModel.VOLUME_ADJUSTED,
        measurement_noise=500.0
    )

    kf_parkinson = AdaptiveKalmanFilter(
        model=KalmanFilterModel.PARKINSON_ADJUSTED,
        measurement_noise=500.0
    )

    # Generate data
    np.random.seed(42)
    base_price = 100.0

    print(f"{'Bar':<6} {'Price':<10} {'Standard':<12} {'Volume':<12} {'Parkinson':<12}")
    print("-" * 70)

    for i in range(15):
        # Price data
        close = Decimal(str(round(base_price + i * 0.5 + np.random.randn() * 0.3, 2)))
        high = Decimal(str(round(float(close) + 0.5, 2)))
        low = Decimal(str(round(float(close) - 0.5, 2)))
        volume = Decimal(str(int(1000000 * (0.8 + np.random.rand() * 0.4))))

        # Update all filters
        f_standard, _ = kf_standard.update(close=close)
        f_volume, _ = kf_volume.update(close=close, volume=volume)
        f_parkinson, _ = kf_parkinson.update(close=close, high=high, low=low)

        print(f"{i:<6} {float(close):<10.2f} {float(f_standard):<12.2f} "
              f"{float(f_volume):<12.2f} {float(f_parkinson):<12.2f}")

    print("\nAll models track the trend but with different responsiveness.")


if __name__ == "__main__":
    demo_basic_usage()
    demo_volume_adjusted()
    demo_parkinson_adjusted()
    demo_model_comparison()

    print("\n=== Demo Complete ===\n")
    print("The Adaptive Kalman Filter is ready for use in trading strategies!")
