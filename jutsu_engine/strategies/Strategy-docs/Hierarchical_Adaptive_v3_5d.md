

## Instructions for Claude Code: Add Cell 1 Exit Confirmation Lag Feature

### Overview
Add a configurable feature to the Hierarchical_Adaptive_v3_5b strategy that requires T_norm to stay below the bull threshold for N consecutive days before exiting Cell 1. This prevents premature exits during brief pullbacks in the current low-volatility, mean-reverting market.

### Requirements

1. **Add new config parameters** in the strategy config YAML:
```yaml
# Cell 1 Exit Confirmation
cell1_exit_confirmation_enabled: true  # Flag to enable/disable this feature
cell1_exit_confirmation_days: 2        # Number of consecutive days T_norm must be below bull_threshold before exiting Cell 1
```

2. **Implementation Logic**:
   - When `cell1_exit_confirmation_enabled` is `false`: Strategy behaves exactly as current (exit Cell 1 immediately when T_norm drops below `t_norm_bull_threshold`)
   - When `cell1_exit_confirmation_enabled` is `true`: 
     - Track consecutive days where T_norm < `t_norm_bull_threshold`
     - Only exit Cell 1 (transition to Cell 3) when the count reaches `cell1_exit_confirmation_days`
     - Reset the counter when T_norm goes back above `t_norm_bull_threshold`
     - This ONLY affects exits FROM Cell 1 - entries and other cell transitions remain unchanged

3. **State Management**:
   - Add a counter variable (e.g., `cell1_exit_pending_days`) to track consecutive days below threshold
   - Initialize to 0
   - Increment when in Cell 1 AND T_norm < bull_threshold
   - Reset to 0 when T_norm >= bull_threshold OR when not in Cell 1

4. **Pseudocode for the logic**:
```python
# During regime determination, after calculating T_norm:

if cell1_exit_confirmation_enabled:
    if current_regime == "Cell_1" and t_norm < t_norm_bull_threshold:
        cell1_exit_pending_days += 1
        if cell1_exit_pending_days >= cell1_exit_confirmation_days:
            # Allow exit to Cell 3 (Sideways/Low)
            new_regime = determine_regime_normally()
            cell1_exit_pending_days = 0
        else:
            # Stay in Cell 1, don't exit yet
            new_regime = "Cell_1"
    else:
        cell1_exit_pending_days = 0
        new_regime = determine_regime_normally()
else:
    # Original behavior
    new_regime = determine_regime_normally()
```

5. **Testing Requirements**:
   - Run backtest with `cell1_exit_confirmation_enabled: false` - results should match current golden config exactly
   - Run backtest with `cell1_exit_confirmation_enabled: true` and `cell1_exit_confirmation_days: 2`
   - Run backtest with `cell1_exit_confirmation_enabled: true` and `cell1_exit_confirmation_days: 3`

6. **Files to Modify**:
   - The main strategy file that implements Hierarchical_Adaptive_v3_5b
   - The config YAML schema/defaults

7. **Important Constraints**:
   - Do NOT change any existing thresholds or parameters
   - Do NOT modify entry logic - only exit logic from Cell 1
   - Ensure backward compatibility - when flag is disabled, behavior must be identical to current

### Expected Outcome
This feature should reduce whipsaw exits during brief T_norm dips, keeping the strategy in Cell 1 (60% TQQQ + 40% QQQ) longer during the post-June 2023 mean-reverting market regime.

---

Copy and paste these instructions to Claude Code. After implementation, we can run a grid search varying `cell1_exit_confirmation_days` from 1-5 to find the optimal value.