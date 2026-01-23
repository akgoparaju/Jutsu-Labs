"""
Scheduler Service for Jutsu Trading Dashboard

Provides UI-controlled scheduling for automated trading execution.
Uses APScheduler for job management with persistence.

Features:
- Enable/disable scheduled execution from UI
- Manual trigger override
- Market hours awareness (NYSE calendar)
- Persistent state across API restarts
- Configurable execution times

Execution Time Mapping:
- 'open': 9:30 AM EST
- '15min_after_open': 9:45 AM EST
- '15min_before_close': 3:45 PM EST
- '5min_before_close': 3:55 PM EST
- 'close': 4:00 PM EST
"""

import json
import logging
import asyncio
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from threading import Lock

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from jutsu_engine.utils.config import get_database_url

logger = logging.getLogger('API.SCHEDULER')

# Eastern timezone for market hours
EASTERN = pytz.timezone('US/Eastern')

# Execution time to EST time mapping
EXECUTION_TIME_MAP: Dict[str, time] = {
    'open': time(9, 30),
    '15min_after_open': time(9, 45),
    '15min_before_close': time(15, 45),
    '5min_before_close': time(15, 55),
    'close': time(16, 0),
}


class SchedulerState:
    """
    Persistent scheduler state.

    Stores scheduler configuration that survives API restarts.
    Uses a JSON file for simple persistence.

    Note: Implements __getstate__/__setstate__ to support pickling when used
    with APScheduler's SQLAlchemyJobStore (threading.Lock cannot be pickled).
    """

    def __init__(self, state_file: Path = Path('state/scheduler_state.json')):
        self.state_file = state_file
        self._lock = Lock()
        self._state: Dict[str, Any] = {
            'enabled': False,
            'execution_time': '15min_after_open',
            'last_run': None,
            'last_run_status': None,
            'last_error': None,
            'run_count': 0,
        }
        self._load_state()

    def __getstate__(self):
        """Return state for pickling, excluding the Lock object.

        Note: pathlib.Path objects can fail to pickle/unpickle correctly in Python 3.11+
        due to internal module changes. We convert Path to str to avoid:
        'ModuleNotFoundError: No module named pathlib._local'

        Fix 2026-01-20: Resolves job corruption that caused hourly refresh to stop.
        """
        state = self.__dict__.copy()
        # Remove the lock - it cannot be pickled
        del state['_lock']
        # Convert Path to string to avoid pickle issues with pathlib in Python 3.11+
        if 'state_file' in state and hasattr(state['state_file'], '__fspath__'):
            state['state_file'] = str(state['state_file'])
        return state

    def __setstate__(self, state):
        """Restore state from pickle, recreating the Lock object."""
        self.__dict__.update(state)
        # Recreate the lock after unpickling
        self._lock = Lock()
        # Convert state_file back to Path if it was stored as string
        if hasattr(self, 'state_file') and isinstance(self.state_file, str):
            self.state_file = Path(self.state_file)

    def _load_state(self):
        """Load state from file if exists."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    loaded = json.load(f)
                    self._state.update(loaded)
                logger.info(f"Scheduler state loaded from {self.state_file}")
            except Exception as e:
                logger.warning(f"Failed to load scheduler state: {e}")

    def _save_state(self):
        """Save state to file."""
        try:
            # Ensure directory exists
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file then rename (atomic)
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(self._state, f, indent=2, default=str)
            temp_file.rename(self.state_file)

            logger.debug(f"Scheduler state saved to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save scheduler state: {e}")

    @property
    def enabled(self) -> bool:
        return self._state.get('enabled', False)

    @enabled.setter
    def enabled(self, value: bool):
        with self._lock:
            self._state['enabled'] = value
            self._save_state()

    @property
    def execution_time(self) -> str:
        return self._state.get('execution_time', '15min_after_open')

    @execution_time.setter
    def execution_time(self, value: str):
        if value not in EXECUTION_TIME_MAP:
            raise ValueError(f"Invalid execution_time: {value}. Must be one of {list(EXECUTION_TIME_MAP.keys())}")
        with self._lock:
            self._state['execution_time'] = value
            self._save_state()

    @property
    def last_run(self) -> Optional[str]:
        return self._state.get('last_run')

    @property
    def last_run_status(self) -> Optional[str]:
        return self._state.get('last_run_status')

    @property
    def last_error(self) -> Optional[str]:
        return self._state.get('last_error')

    @property
    def run_count(self) -> int:
        return self._state.get('run_count', 0)

    def record_run(self, status: str, error: Optional[str] = None):
        """Record a scheduler run."""
        with self._lock:
            self._state['last_run'] = datetime.now(timezone.utc).isoformat()
            self._state['last_run_status'] = status
            self._state['last_error'] = error
            self._state['run_count'] = self._state.get('run_count', 0) + 1
            self._save_state()

    def to_dict(self) -> Dict[str, Any]:
        """Return state as dictionary."""
        return self._state.copy()


class SchedulerService:
    """
    Scheduler service for automated trading execution.

    Manages APScheduler jobs for scheduled daily trading runs and data refresh.
    Respects market hours and trading days.
    
    Jobs:
    1. Trading Job: Runs at execution time (e.g., 9:45 AM EST) - full trading workflow
    2. Data Refresh Job: Runs at market close (4:00 PM EST) - price/P&L updates only
    """

    _instance: Optional['SchedulerService'] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        state_file: Optional[Path] = None,
        config_loader: Optional[Callable[[], Dict]] = None,
    ):
        if self._initialized:
            return

        self.state = SchedulerState(
            state_file=state_file or Path('state/scheduler_state.json')
        )
        self._config_loader = config_loader
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job_id = 'daily_trading_job'
        self._refresh_job_id = 'market_close_refresh_job'  # Market close refresh job
        self._hourly_refresh_job_id = 'hourly_refresh_job'  # Hourly price refresh job
        self._token_check_job_id = 'token_expiration_check_job'  # Schwab token monitoring
        self._is_running_job = False
        self._is_running_refresh = False  # Track refresh job state
        self._is_running_hourly_refresh = False  # Track hourly refresh state
        self._initialized = True

        logger.info("SchedulerService initialized")

    def __getstate__(self):
        """
        Return state for pickling, excluding non-pickleable objects.
        
        APScheduler's SQLAlchemyJobStore pickles job functions (instance methods),
        which requires pickling the entire SchedulerService instance.
        The AsyncIOScheduler cannot be pickled, so we exclude it.
        
        Architecture fix 2026-01-15: Resolves "Schedulers cannot be serialized" error
        that was preventing hourly and market close refresh jobs from executing.
        
        Architecture fix 2026-01-23: DO NOT set _scheduler to None in state,
        as this was causing race conditions where the singleton's _scheduler
        attribute was being reset during job store operations.
        """
        state = self.__dict__.copy()
        # Remove non-pickleable objects entirely (don't set to None)
        if '_scheduler' in state:
            del state['_scheduler']
        if '_config_loader' in state:
            del state['_config_loader']
        return state

    def __setstate__(self, state):
        """
        Restore state from pickle.
        
        After unpickling, the scheduler will be None and needs to be
        re-initialized by calling start() if needed.
        """
        self.__dict__.update(state)
        # Re-initialize non-pickleable objects to None (they'll be set by start())
        if '_scheduler' not in self.__dict__:
            self._scheduler = None
        if '_config_loader' not in self.__dict__:
            self._config_loader = None

    def _get_execution_time(self) -> str:
        """
        Get execution time from config with database overrides.

        Priority:
        1. Database override (if active)
        2. YAML config file
        3. State file fallback
        """
        # Check database overrides first (highest priority)
        try:
            from jutsu_engine.api.dependencies import SessionLocal
            from jutsu_engine.data.models import ConfigOverride

            db = SessionLocal()
            try:
                override = db.query(ConfigOverride).filter(
                    ConfigOverride.parameter_name == 'execution_time',
                    ConfigOverride.is_active == True
                ).first()

                if override:
                    logger.debug(f"Using execution_time from database override: {override.override_value}")
                    return override.override_value
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to check database overrides: {e}")

        # Fall back to config file
        if self._config_loader:
            try:
                config = self._config_loader()
                strategy_params = config.get('strategy', {}).get('parameters', {})
                return strategy_params.get('execution_time', self.state.execution_time)
            except Exception as e:
                logger.warning(f"Failed to load execution_time from config: {e}")

        return self.state.execution_time

    def _get_cron_trigger(self, execution_time_key: str) -> CronTrigger:
        """
        Create a CronTrigger for the given execution time.

        Runs Monday-Friday at the specified EST time.
        """
        est_time = EXECUTION_TIME_MAP.get(execution_time_key)
        if not est_time:
            logger.warning(f"Unknown execution_time '{execution_time_key}', defaulting to 15min_after_open")
            est_time = EXECUTION_TIME_MAP['15min_after_open']

        return CronTrigger(
            hour=est_time.hour,
            minute=est_time.minute,
            day_of_week='mon-fri',
            timezone=EASTERN,
        )

    async def _execute_trading_job(self):
        """
        Execute the daily trading job.

        Checks market hours and calls the daily_multi_strategy_run main function
        to execute all active strategies in parallel.
        """
        if self._is_running_job:
            logger.warning("Job already running, skipping")
            return

        self._is_running_job = True

        try:
            logger.info("=" * 60)
            logger.info("Multi-Strategy Trading Job Starting")
            logger.info("=" * 60)

            # Check if it's a trading day
            from jutsu_engine.live.market_calendar import is_trading_day

            if not is_trading_day():
                logger.info("Not a trading day - skipping execution")
                self.state.record_run('skipped', 'Not a trading day')
                return

            # Import and run the multi-strategy main function
            try:
                # Import inside to avoid circular imports
                import sys
                from pathlib import Path

                # Ensure scripts directory is in path
                scripts_path = Path(__file__).parent.parent.parent / 'scripts'
                if str(scripts_path) not in sys.path:
                    sys.path.insert(0, str(scripts_path))

                from scripts.daily_multi_strategy_run import main as multi_strategy_main

                # Run the multi-strategy trading workflow
                # Note: This runs synchronously - for production, consider
                # running in a thread pool to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: multi_strategy_main(check_freshness=True)
                )

                logger.info("Multi-strategy trading job completed successfully")
                self.state.record_run('success')

            except Exception as e:
                logger.error(f"Multi-strategy trading job failed: {e}", exc_info=True)
                self.state.record_run('failed', str(e))

        finally:
            self._is_running_job = False

    async def _execute_data_refresh_job(self):
        """
        Execute the market close data refresh job.
        
        Updates position prices, calculates P&L, and saves performance snapshot
        WITHOUT running the trading strategy or executing any trades.
        
        This runs at market close (4:00 PM EST) regardless of whether
        trades happened during the day.
        """
        if self._is_running_refresh:
            logger.warning("Refresh job already running, skipping")
            return
        
        self._is_running_refresh = True
        
        try:
            logger.info("=" * 60)
            logger.info("Market Close Data Refresh Starting")
            logger.info("=" * 60)
            
            # Check if it's a trading day
            from jutsu_engine.live.market_calendar import is_trading_day
            
            if not is_trading_day():
                logger.info("Not a trading day - skipping data refresh")
                return
            
            try:
                from jutsu_engine.live.data_refresh import get_data_refresher
                from jutsu_engine.live.strategy_registry import StrategyRegistry
                
                # Load active strategies from registry
                registry = StrategyRegistry()
                active_strategies = registry.get_active_strategies()
                strategy_ids = [s.id for s in active_strategies]
                
                logger.info(f"Refreshing data for {len(strategy_ids)} strategies: {strategy_ids}")
                
                refresher = get_data_refresher()
                
                # Perform full refresh for ALL active strategies
                results = await refresher.full_refresh(
                    sync_data=True,
                    calculate_ind=True,
                    strategy_ids=strategy_ids,
                )
                
                if results['success']:
                    logger.info("Market close data refresh completed successfully")
                    # Notify frontend via WebSocket to refresh data
                    try:
                        from jutsu_engine.api.websocket import broadcast_data_refresh
                        await broadcast_data_refresh({
                            'refresh_type': 'market_close',
                            'strategies': strategy_ids,
                        })
                        logger.debug("WebSocket data_refresh broadcast sent (market close)")
                    except Exception as e:
                        logger.warning(f"Failed to broadcast data refresh: {e}")
                else:
                    logger.warning(f"Data refresh completed with errors: {results['errors']}")
                
            except Exception as e:
                logger.error(f"Data refresh job failed: {e}", exc_info=True)
        
        finally:
            self._is_running_refresh = False

    async def _execute_hourly_refresh_job(self):
        """
        Execute the hourly data refresh job during market hours.

        Updates position prices and calculates P&L WITHOUT saving a snapshot.
        This provides intraday price updates while the market is open.

        Market hours check: Only runs 10:00 AM - 3:30 PM EST (not close to market close)
        The 4:00 PM market close refresh handles end-of-day snapshot.
        """
        if self._is_running_hourly_refresh or self._is_running_refresh:
            logger.debug("Hourly refresh skipped - another refresh already running")
            return

        self._is_running_hourly_refresh = True

        try:
            # Check if within market hours (10:00 AM - 3:30 PM EST)
            # Skip if close to market close (4 PM handled by separate job)
            now_est = datetime.now(EASTERN)

            # Only run during market hours (skip before 10 AM and after 3:30 PM)
            if now_est.hour < 10 or (now_est.hour >= 15 and now_est.minute >= 30) or now_est.hour >= 16:
                logger.debug(f"Outside hourly refresh window ({now_est.strftime('%I:%M %p EST')}) - skipping")
                return

            # Check weekday (0=Monday, 4=Friday)
            if now_est.weekday() > 4:
                logger.debug("Weekend - skipping hourly refresh")
                return

            # Check if it's a trading day
            from jutsu_engine.live.market_calendar import is_trading_day

            if not is_trading_day():
                logger.debug("Not a trading day - skipping hourly refresh")
                return

            logger.info(f"Hourly Data Refresh Starting ({now_est.strftime('%I:%M %p EST')})")

            try:
                from jutsu_engine.live.data_refresh import get_data_refresher
                from jutsu_engine.live.strategy_registry import StrategyRegistry
                
                # Load active strategies from registry
                registry = StrategyRegistry()
                active_strategies = registry.get_active_strategies()
                strategy_ids = [s.id for s in active_strategies]
                
                logger.debug(f"Hourly refresh for strategies: {strategy_ids}")

                refresher = get_data_refresher()

                # Perform refresh for ALL active strategies
                # Note: full_refresh saves snapshots - consider adding a flag to skip if needed
                results = await refresher.full_refresh(
                    sync_data=True,
                    calculate_ind=False,  # Skip indicators for hourly refresh
                    strategy_ids=strategy_ids,
                )

                if results['success']:
                    logger.info(f"Hourly refresh completed successfully ({now_est.strftime('%I:%M %p EST')})")
                    # Notify frontend via WebSocket to refresh data
                    try:
                        from jutsu_engine.api.websocket import broadcast_data_refresh
                        await broadcast_data_refresh({
                            'refresh_type': 'hourly',
                            'strategies': strategy_ids,
                        })
                        logger.debug("WebSocket data_refresh broadcast sent")
                    except Exception as e:
                        logger.warning(f"Failed to broadcast data refresh: {e}")
                else:
                    logger.warning(f"Hourly refresh completed with errors: {results['errors']}")

            except Exception as e:
                logger.error(f"Hourly refresh job failed: {e}", exc_info=True)

        finally:
            self._is_running_hourly_refresh = False

    async def _check_token_expiration_job(self):
        """
        Check Schwab token expiration and send notifications.
        
        Runs every 12 hours. Sends notifications at these thresholds:
        - 5 days remaining: INFO notification
        - 2 days remaining: WARNING notification  
        - 1 day remaining: CRITICAL notification
        - 12 hours remaining: URGENT notification
        - Expired: CRITICAL expired alert
        
        Notification thresholds are tracked to avoid duplicate alerts.
        """
        logger.info("Checking Schwab token expiration status...")
        
        try:
            # Import token status checker
            from jutsu_engine.api.routes.schwab_auth import get_token_status
            from jutsu_engine.utils.notifications import (
                send_token_expiration_warning,
                send_token_expired_alert,
            )
            
            token_status = get_token_status()
            
            if not token_status['token_exists']:
                logger.info("No Schwab token found - skipping expiration check")
                return
            
            expires_in_days = token_status.get('expires_in_days')
            
            if expires_in_days is None:
                logger.warning("Could not determine token expiration - legacy token format?")
                return
            
            # Log current status
            if expires_in_days > 0:
                logger.info(f"Schwab token expires in {expires_in_days:.1f} days")
            else:
                logger.warning(f"Schwab token is EXPIRED ({abs(expires_in_days):.1f} days ago)")
            
            # Track which notifications we've sent to avoid duplicates
            # Use state file for persistence
            notification_state = self._get_token_notification_state()
            
            # Determine if we should send a notification
            should_notify = False
            notification_level = None
            
            if expires_in_days <= 0:
                # Token expired
                if notification_state.get('expired_notified') != True:
                    send_token_expired_alert()
                    self._update_token_notification_state({'expired_notified': True})
                    logger.info("Sent token expired notification")
                return
            
            # Check thresholds (notify once per threshold)
            if expires_in_days <= 0.5:  # 12 hours
                notification_level = '12h'
            elif expires_in_days <= 1:
                notification_level = '1d'
            elif expires_in_days <= 2:
                notification_level = '2d'
            elif expires_in_days <= 5:
                notification_level = '5d'
            
            if notification_level:
                last_level = notification_state.get('last_notification_level')
                level_order = ['5d', '2d', '1d', '12h']
                
                # Only notify if this is a more urgent level than last notification
                if last_level is None or (
                    notification_level in level_order and 
                    (last_level not in level_order or 
                     level_order.index(notification_level) > level_order.index(last_level))
                ):
                    success = send_token_expiration_warning(expires_in_days)
                    if success:
                        self._update_token_notification_state({
                            'last_notification_level': notification_level,
                            'last_notification_time': datetime.now(timezone.utc).isoformat(),
                            'expired_notified': False,  # Reset expired flag
                        })
                        logger.info(f"Sent token expiration warning ({notification_level})")
                    else:
                        logger.debug("Notification not sent (webhook not configured or disabled)")
            else:
                logger.debug("Token has sufficient time remaining, no notification needed")
                
        except Exception as e:
            logger.error(f"Token expiration check failed: {e}", exc_info=True)
    
    def _get_token_notification_state(self) -> dict:
        """Load token notification state from file."""
        state_file = Path('state/token_notification_state.json')
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _update_token_notification_state(self, updates: dict):
        """Update token notification state file."""
        state_file = Path('state/token_notification_state.json')
        try:
            state = self._get_token_notification_state()
            state.update(updates)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save notification state: {e}")

    def start(self, max_retries: int = 5, initial_delay: float = 2.0):
        """
        Start the scheduler with retry logic for database connection.
        
        Architecture fix 2026-01-21: Added retry logic to handle race condition
        where container starts before database is ready. This prevents the
        scheduler from being permanently broken due to transient DB unavailability.
        
        Args:
            max_retries: Maximum number of connection attempts (default: 5)
            initial_delay: Initial delay between retries in seconds (default: 2.0)
                          Uses exponential backoff: 2, 4, 8, 16, 32 seconds
        """
        if self._scheduler is not None and self._scheduler.running:
            logger.info("Scheduler already running")
            return True
        
        # Clean up any previous failed scheduler instance
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
            self._scheduler = None

        # Configure scheduler with persistent job store (SQLAlchemy)
        # Architecture decision 2026-01-14: Use SQLAlchemyJobStore to prevent
        # job loss on server restart (MemoryJobStore loses jobs)
        #
        # Default misfire_grace_time of 1 second is too strict - jobs get marked
        # as "missed" if event loop is delayed by network I/O, database queries, etc.
        # 300 seconds (5 minutes) allows for temporary delays while still
        # catching truly missed executions.
        
        delay = initial_delay
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                database_url = get_database_url()
                jobstore = SQLAlchemyJobStore(url=database_url)
                logger.info(f"Using SQLAlchemyJobStore for persistent job scheduling (attempt {attempt})")
                
                self._scheduler = AsyncIOScheduler(
                    jobstores={'default': jobstore},
                    timezone=EASTERN,
                    job_defaults={
                        'misfire_grace_time': 300,  # 5 minutes grace period
                        'coalesce': True,           # Combine multiple missed runs into one
                        'max_instances': 1,         # Only one instance at a time
                    },
                )

                # Add job if scheduler is enabled
                if self.state.enabled:
                    self._add_job()

                self._scheduler.start()
                logger.info("Scheduler started")
                return True
                
            except Exception as e:
                last_error = e
                logger.warning(f"Scheduler start attempt {attempt}/{max_retries} failed: {e}")
                
                # Clean up failed scheduler
                if self._scheduler is not None:
                    try:
                        self._scheduler.shutdown(wait=False)
                    except Exception:
                        pass
                    self._scheduler = None
                
                if attempt < max_retries:
                    logger.info(f"Retrying in {delay:.1f} seconds...")
                    import time as time_module
                    time_module.sleep(delay)
                    delay *= 2  # Exponential backoff
        
        # All retries failed - fall back to MemoryJobStore
        logger.error(
            f"All {max_retries} attempts to connect to database failed. "
            f"Last error: {last_error}. Falling back to MemoryJobStore (jobs will be lost on restart)."
        )
        
        try:
            jobstore = MemoryJobStore()
            self._scheduler = AsyncIOScheduler(
                jobstores={'default': jobstore},
                timezone=EASTERN,
                job_defaults={
                    'misfire_grace_time': 300,
                    'coalesce': True,
                    'max_instances': 1,
                },
            )
            
            if self.state.enabled:
                self._add_job()
            
            self._scheduler.start()
            logger.warning("Scheduler started with MemoryJobStore (degraded mode)")
            return True
            
        except Exception as e:
            logger.critical(f"Failed to start scheduler even with MemoryJobStore: {e}")
            return False

    def ensure_running(self) -> bool:
        """
        Ensure the scheduler is running, attempting to start it if not.
        
        Architecture fix 2026-01-21: This method provides self-healing capability.
        If the scheduler failed to start at startup (e.g., database unavailable),
        this method can be called later to attempt recovery.
        
        Returns:
            True if scheduler is running (was already running or successfully started)
            False if scheduler could not be started
        """
        if self._scheduler is not None and self._scheduler.running:
            return True
        
        logger.info("Scheduler not running, attempting to start...")
        return self.start(max_retries=3, initial_delay=1.0)
    
    def is_healthy(self) -> bool:
        """
        Check if the scheduler is healthy.
        
        A healthy scheduler:
        - Has been started
        - Is currently running
        - Can retrieve job information without errors
        
        Returns:
            True if scheduler is healthy, False otherwise
        """
        if self._scheduler is None:
            return False
        
        if not self._scheduler.running:
            return False
        
        # Try to get a job to verify jobstore is accessible
        try:
            job = self._scheduler.get_job(self._job_id)
            # If job exists, verify it has required attributes
            if job is not None:
                # Access next_run_time to verify job is not corrupted
                _ = job.next_run_time
            return True
        except AttributeError as e:
            # Job object is corrupted (e.g., "'Job' object has no attribute 'next_run_time'")
            logger.warning(f"Scheduler health check failed - corrupted job object: {e}")
            return False
        except Exception as e:
            logger.warning(f"Scheduler health check failed: {e}")
            return False

    def stop(self):
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped")

    def _add_job(self):
        """Add the trading job and data refresh job to the scheduler."""
        if self._scheduler is None:
            return

        # Remove existing jobs if present
        self._remove_job()

        # Add trading job at execution time
        execution_time = self._get_execution_time()
        trigger = self._get_cron_trigger(execution_time)

        self._scheduler.add_job(
            self._execute_trading_job,
            trigger=trigger,
            id=self._job_id,
            name='Daily Trading Execution',
            replace_existing=True,
            coalesce=True,  # Skip missed runs
            max_instances=1,  # Only one instance at a time
        )

        logger.info(f"Trading job scheduled: {execution_time} EST (Mon-Fri)")
        
        # Add market close refresh job at 4:00 PM EST
        close_trigger = self._get_cron_trigger('close')
        
        self._scheduler.add_job(
            self._execute_data_refresh_job,
            trigger=close_trigger,
            id=self._refresh_job_id,
            name='Market Close Data Refresh',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        
        logger.info("Data refresh job scheduled: 4:00 PM EST (Mon-Fri)")

        # Add hourly refresh job (runs every 1 hour)
        # The job will self-check if within market hours before executing
        hourly_trigger = IntervalTrigger(hours=1, timezone=EASTERN)

        self._scheduler.add_job(
            self._execute_hourly_refresh_job,
            trigger=hourly_trigger,
            id=self._hourly_refresh_job_id,
            name='Hourly Price Refresh',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        logger.info("Hourly refresh job scheduled: Every 1 hour (market hours only: 10 AM - 3:30 PM EST)")

        # Add token expiration check job (runs every 12 hours)
        # Monitors Schwab OAuth token and sends notifications before expiration
        token_check_trigger = IntervalTrigger(hours=12, timezone=EASTERN)

        self._scheduler.add_job(
            self._check_token_expiration_job,
            trigger=token_check_trigger,
            id=self._token_check_job_id,
            name='Schwab Token Expiration Monitor',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        logger.info("Token expiration check job scheduled: Every 12 hours")

    def _remove_job(self):
        """Remove the trading job, data refresh job, hourly refresh job, and token check job from the scheduler."""
        if self._scheduler is None:
            return

        try:
            self._scheduler.remove_job(self._job_id)
            logger.info("Trading job removed from scheduler")
        except Exception:
            pass  # Job may not exist

        try:
            self._scheduler.remove_job(self._refresh_job_id)
            logger.info("Data refresh job removed from scheduler")
        except Exception:
            pass  # Job may not exist

        try:
            self._scheduler.remove_job(self._hourly_refresh_job_id)
            logger.info("Hourly refresh job removed from scheduler")
        except Exception:
            pass  # Job may not exist

        try:
            self._scheduler.remove_job(self._token_check_job_id)
            logger.info("Token expiration check job removed from scheduler")
        except Exception:
            pass  # Job may not exist  # Job may not exist

    def enable(self) -> Dict[str, Any]:
        """
        Enable scheduled execution.

        Returns:
            Status dict with enabled state and next run time
        """
        self.state.enabled = True

        if self._scheduler is not None and self._scheduler.running:
            self._add_job()

        logger.info("Scheduler enabled")
        return self.get_status()

    def disable(self) -> Dict[str, Any]:
        """
        Disable scheduled execution.

        Returns:
            Status dict with disabled state
        """
        self.state.enabled = False
        self._remove_job()

        logger.info("Scheduler disabled")
        return self.get_status()

    async def trigger_now(self) -> Dict[str, Any]:
        """
        Manually trigger execution immediately.

        Returns:
            Result dict with execution status
        """
        logger.info("Manual trigger requested")

        if self._is_running_job:
            return {
                'success': False,
                'message': 'A job is already running',
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

        # Execute the job
        await self._execute_trading_job()

        return {
            'success': True,
            'message': 'Trading job triggered manually',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': self.state.last_run_status,
            'error': self.state.last_error,
        }

    def get_next_run_time(self) -> Optional[str]:
        """Get the next scheduled run time."""
        if self._scheduler is None or not self.state.enabled:
            # Early return if scheduler not ready
            logger.debug(f"get_next_run_time: scheduler not initialized or disabled")
            return None
        
        if not self._scheduler.running:
            logger.debug(f"get_next_run_time: scheduler not running")
            return None

        try:
            job = self._scheduler.get_job(self._job_id)
            logger.debug(f"get_next_run_time: job={job}, job_id={self._job_id}")
            if job and hasattr(job, 'next_run_time') and job.next_run_time:
                return job.next_run_time.isoformat()
            elif job:
                logger.warning(f"Job {self._job_id} exists but has no next_run_time: {job}")
            else:
                logger.warning(f"Job {self._job_id} not found in scheduler")
        except AttributeError as e:
            # Job object is corrupted - this indicates jobstore issues
            logger.warning(f"Failed to get next run time (corrupted job): {e}")
        except Exception as e:
            logger.warning(f"Failed to get next run time: {e}")

        return None

    def get_status(self) -> Dict[str, Any]:
        """
        Get scheduler status.

        Returns:
            Complete status dict including:
            - enabled: Whether scheduler is enabled
            - execution_time: Configured execution time key
            - execution_time_est: Human-readable EST time
            - next_run: Next scheduled run (ISO format)
            - next_refresh: Next market close refresh (ISO format)
            - last_run: Last execution time (ISO format)
            - last_run_status: success, failed, skipped
            - last_error: Error message if last run failed
            - run_count: Total number of runs
            - is_running: Whether a job is currently executing
            - is_running_refresh: Whether data refresh is running
            - scheduler_running: Whether the scheduler process is running
            - scheduler_healthy: Whether the scheduler is healthy
        """
        execution_time = self._get_execution_time()
        est_time = EXECUTION_TIME_MAP.get(execution_time, time(9, 45))
        
        # Check scheduler health
        scheduler_running = self._scheduler is not None and self._scheduler.running
        scheduler_healthy = self.is_healthy()

        return {
            'enabled': self.state.enabled,
            'execution_time': execution_time,
            'execution_time_est': est_time.strftime('%I:%M %p EST'),
            'next_run': self.get_next_run_time(),
            'next_refresh': self._get_next_refresh_time(),
            'next_hourly_refresh': self._get_next_hourly_refresh_time(),
            'last_run': self.state.last_run,
            'last_run_status': self.state.last_run_status,
            'last_error': self.state.last_error,
            'run_count': self.state.run_count,
            'is_running': self._is_running_job,
            'is_running_refresh': self._is_running_refresh,
            'is_running_hourly_refresh': self._is_running_hourly_refresh,
            'valid_execution_times': list(EXECUTION_TIME_MAP.keys()),
            'scheduler_running': scheduler_running,
            'scheduler_healthy': scheduler_healthy,
        }
    
    def _get_next_refresh_time(self) -> Optional[str]:
        """Get the next scheduled data refresh time."""
        if self._scheduler is None or not self.state.enabled:
            return None
        
        if not self._scheduler.running:
            return None

        try:
            job = self._scheduler.get_job(self._refresh_job_id)
            if job and hasattr(job, 'next_run_time') and job.next_run_time:
                return job.next_run_time.isoformat()
        except AttributeError as e:
            logger.warning(f"Failed to get next refresh time (corrupted job): {e}")
        except Exception as e:
            logger.warning(f"Failed to get next refresh time: {e}")

        return None

    def _get_next_hourly_refresh_time(self) -> Optional[str]:
        """Get the next scheduled hourly refresh time."""
        if self._scheduler is None or not self.state.enabled:
            return None
        
        if not self._scheduler.running:
            return None

        try:
            job = self._scheduler.get_job(self._hourly_refresh_job_id)
            if job and hasattr(job, 'next_run_time') and job.next_run_time:
                return job.next_run_time.isoformat()
        except AttributeError as e:
            logger.warning(f"Failed to get next hourly refresh time (corrupted job): {e}")
        except Exception as e:
            logger.warning(f"Failed to get next hourly refresh time: {e}")

        return None
    
    async def trigger_data_refresh(self) -> Dict[str, Any]:
        """
        Manually trigger a data refresh immediately.
        
        Updates prices, P&L, and saves performance snapshot
        WITHOUT running the trading strategy.
        
        Returns:
            Result dict with refresh status
        """
        logger.info("Manual data refresh triggered")
        
        if self._is_running_refresh:
            return {
                'success': False,
                'message': 'A refresh is already running',
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        
        try:
            from jutsu_engine.live.data_refresh import get_data_refresher
            
            refresher = get_data_refresher()
            results = await refresher.full_refresh(
                sync_data=True,
                calculate_ind=True,
            )
            
            return {
                'success': results['success'],
                'message': 'Data refresh completed' if results['success'] else 'Data refresh had errors',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'details': results,
            }
            
        except Exception as e:
            logger.error(f"Manual data refresh failed: {e}", exc_info=True)
            return {
                'success': False,
                'message': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

    def update_execution_time(self, execution_time: str) -> Dict[str, Any]:
        """
        Update the execution time.

        Args:
            execution_time: One of the valid execution time keys

        Returns:
            Updated status dict
        """
        if execution_time not in EXECUTION_TIME_MAP:
            raise ValueError(
                f"Invalid execution_time: {execution_time}. "
                f"Must be one of {list(EXECUTION_TIME_MAP.keys())}"
            )

        self.state.execution_time = execution_time

        # Reschedule if enabled
        if self.state.enabled and self._scheduler is not None:
            self._add_job()

        logger.info(f"Execution time updated to: {execution_time}")
        return self.get_status()


# Singleton instance getter
_scheduler_service: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    """
    Get the singleton scheduler service instance.
    
    Ensures the scheduler is started if the service exists but the scheduler
    is not running. This handles the case where uvicorn reload kills the worker
    process, resetting the module-level singleton, but the scheduler needs to
    be restarted in the new worker.
    """
    global _scheduler_service

    if _scheduler_service is None:
        from jutsu_engine.api.dependencies import load_config
        _scheduler_service = SchedulerService(config_loader=load_config)
    
    # Ensure scheduler is started (handles uvicorn reload scenario)
    if _scheduler_service._scheduler is None or not _scheduler_service._scheduler.running:
        logger.info("Scheduler not running, starting it now...")
        _scheduler_service.start()
        logger.info("Scheduler started successfully")

    return _scheduler_service
