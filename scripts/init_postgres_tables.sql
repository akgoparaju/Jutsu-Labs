-- ============================================================================
-- Jutsu Labs PostgreSQL Table Initialization Script
-- ============================================================================
-- Run this ONCE after PostgreSQL upgrade or fresh installation.
-- Safe to run multiple times (uses IF NOT EXISTS).
--
-- Usage from Unraid terminal:
--   docker exec -i PostgreSQL psql -U jutsudB -d jutsu_labs < init_postgres_tables.sql
--
-- Or copy to server and run:
--   psql -h <host> -p 5423 -U jutsudB -d jutsu_labs -f init_postgres_tables.sql
-- ============================================================================

-- Enable better error messages
\set ON_ERROR_STOP on

BEGIN;

-- ============================================================================
-- CORE MARKET DATA TABLES (Original)
-- ============================================================================

CREATE TABLE IF NOT EXISTS market_data (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT NOT NULL,
    data_source VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_symbol_tf_ts
    ON market_data (symbol, timeframe, timestamp);
CREATE INDEX IF NOT EXISTS idx_market_data_lookup
    ON market_data (symbol, timeframe, timestamp);
CREATE INDEX IF NOT EXISTS idx_market_data_symbol
    ON market_data (symbol);
CREATE INDEX IF NOT EXISTS idx_market_data_timestamp
    ON market_data (timestamp);

CREATE TABLE IF NOT EXISTS data_metadata (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    last_bar_timestamp TIMESTAMP WITH TIME ZONE,
    total_bars INTEGER DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_metadata
    ON data_metadata (symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_metadata_lookup
    ON data_metadata (symbol, timeframe);

CREATE TABLE IF NOT EXISTS data_audit_log (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10),
    timeframe VARCHAR(10),
    operation VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    message VARCHAR(500),
    bars_affected INTEGER DEFAULT 0,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
    ON data_audit_log (timestamp);

-- ============================================================================
-- LIVE TRADING TABLES (Phase 0-5)
-- ============================================================================

CREATE TABLE IF NOT EXISTS live_trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    target_price NUMERIC(18, 6) NOT NULL,
    fill_price NUMERIC(18, 6),
    fill_value NUMERIC(18, 6),
    slippage_pct NUMERIC(10, 6),
    schwab_order_id VARCHAR(50),
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    t_norm NUMERIC(10, 6),
    z_score NUMERIC(10, 6),
    reason VARCHAR(50),
    mode VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_live_trades_symbol
    ON live_trades (symbol);
CREATE INDEX IF NOT EXISTS idx_live_trades_timestamp
    ON live_trades (timestamp);
CREATE INDEX IF NOT EXISTS idx_live_trades_mode_ts
    ON live_trades (mode, timestamp);
CREATE INDEX IF NOT EXISTS idx_live_trades_symbol_mode
    ON live_trades (symbol, mode);

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost NUMERIC(18, 6),
    market_value NUMERIC(18, 6),
    unrealized_pnl NUMERIC(18, 6),
    mode VARCHAR(20) NOT NULL,
    last_updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_position_symbol_mode
    ON positions (symbol, mode);
CREATE INDEX IF NOT EXISTS idx_positions_mode
    ON positions (mode);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    total_equity NUMERIC(18, 6) NOT NULL,
    cash NUMERIC(18, 6),
    positions_value NUMERIC(18, 6),
    daily_return NUMERIC(10, 6),
    cumulative_return NUMERIC(10, 6),
    drawdown NUMERIC(10, 6),
    strategy_cell INTEGER,
    trend_state VARCHAR(20),
    vol_state VARCHAR(10),
    positions_json TEXT,
    baseline_value NUMERIC(18, 6),
    baseline_return NUMERIC(10, 6),
    mode VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_perf_snapshot_timestamp
    ON performance_snapshots (timestamp);
CREATE INDEX IF NOT EXISTS idx_perf_snapshot_mode_ts
    ON performance_snapshots (mode, timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS uix_perf_snapshot_mode_ts
    ON performance_snapshots (mode, timestamp);

-- ============================================================================
-- CONFIGURATION TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS config_overrides (
    id SERIAL PRIMARY KEY,
    parameter_name VARCHAR(50) NOT NULL,
    original_value VARCHAR(100),
    override_value VARCHAR(100) NOT NULL,
    value_type VARCHAR(20) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    reason VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deactivated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_config_override_active
    ON config_overrides (parameter_name, is_active);

CREATE TABLE IF NOT EXISTS config_history (
    id SERIAL PRIMARY KEY,
    parameter_name VARCHAR(50) NOT NULL,
    old_value VARCHAR(100),
    new_value VARCHAR(100) NOT NULL,
    change_type VARCHAR(20) NOT NULL,
    changed_by VARCHAR(50),
    reason VARCHAR(200),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_config_history_param
    ON config_history (parameter_name);
CREATE INDEX IF NOT EXISTS idx_config_history_timestamp
    ON config_history (timestamp);

CREATE TABLE IF NOT EXISTS system_state (
    id SERIAL PRIMARY KEY,
    key VARCHAR(50) NOT NULL UNIQUE,
    value TEXT,
    value_type VARCHAR(20),
    -- Renamed from 'last_updated' to 'updated_at' for consistency
    -- SQLAlchemy model also updated to use 'updated_at'
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_state_key
    ON system_state (key);

-- ============================================================================
-- USER AUTHENTICATION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_username
    ON users (username);

COMMIT;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

\echo ''
\echo '============================================'
\echo 'Table Creation Complete!'
\echo '============================================'
\echo ''

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

\echo ''
\echo 'All Jutsu Labs tables have been created.'
\echo 'This script is safe to run multiple times.'
\echo '============================================'
