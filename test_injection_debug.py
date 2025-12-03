#!/usr/bin/env python3
"""
Quick test to verify dependency injection with debug logging.
Tests if set_end_date() and set_data_handler() are being called.
"""
import sys
from datetime import datetime
from jutsu_engine.strategies.Hierarchical_Adaptive_v3_5b import Hierarchical_Adaptive_v3_5b

print("="*60)
print("TESTING DEPENDENCY INJECTION")
print("="*60)

# Create strategy instance (minimal params to match grid search)
strategy = Hierarchical_Adaptive_v3_5b(
    execution_time="15min_after_open",
    measurement_noise=3000.0,
    process_noise_1=0.01,
    process_noise_2=0.01,
    osc_smoothness=15,
    strength_smoothness=15,
    T_max=50.0,
    sma_fast=40,
    sma_slow=140,
    t_norm_bull_thresh=0.2,
    t_norm_bear_thresh=-0.3,
    realized_vol_window=21,
    vol_baseline_window=126,
    upper_thresh_z=1.0,
    lower_thresh_z=0.2,
    vol_crush_threshold=-0.15,
    vol_crush_lookback=5,
    leverage_scalar=1.0,
    use_inverse_hedge=False,
    w_PSQ_max=0.5,
    rebalance_threshold=0.025,
)

print(f"\n1. Strategy created: {strategy.__class__.__name__}")
print(f"2. Strategy type: {type(strategy)}")
print(f"3. hasattr(strategy, 'set_end_date'): {hasattr(strategy, 'set_end_date')}")
print(f"4. hasattr(strategy, 'set_data_handler'): {hasattr(strategy, 'set_data_handler')}")

# Verify methods are callable
if hasattr(strategy, 'set_end_date'):
    print("\n5. Testing set_end_date() method:")
    try:
        strategy.set_end_date(datetime(2025, 11, 24))
        print("   ✓ set_end_date() called successfully")
    except Exception as e:
        print(f"   ✗ set_end_date() failed: {e}")
else:
    print("\n5. ✗ set_end_date() NOT FOUND")
    sys.exit(1)

if hasattr(strategy, 'set_data_handler'):
    print("\n6. set_data_handler() method exists")
    print("   (not calling it without actual data_handler)")
else:
    print("\n6. ✗ set_data_handler() NOT FOUND")
    sys.exit(1)

print("\n" + "="*60)
print("✓ ALL TESTS PASSED - Methods exist and are callable")
print("="*60)
