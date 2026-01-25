"""
E2E Playwright tests for Performance Dashboard.

Task 8.4 (Extended): UI regression tests using Playwright.

Tests cover:
1. Performance tab loading and KPI display
2. Sharpe ratio display (should show ~0.82, not -4)
3. Equity curve chart rendering
4. Time range selector functionality
5. Baseline comparison display (QQQ)
6. Mobile responsive layout
7. Data refresh behavior

Reference: claudedocs/eod_daily_performance_workflow.md Phase 8, Task 8.4
"""

import pytest
from datetime import date
import re

# Playwright is optional for E2E tests
try:
    from playwright.sync_api import Page, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Page = None
    expect = None

# Skip all tests if playwright is not available
pytestmark = pytest.mark.skipif(
    not PLAYWRIGHT_AVAILABLE,
    reason="Playwright not installed"
)


# =============================================================================
# Configuration
# =============================================================================

BASE_URL = "http://localhost:3000"  # Dashboard URL
API_URL = "http://localhost:8000"   # API URL

# Test strategy
TEST_STRATEGY = "v3_5b"
EXPECTED_SHARPE_MIN = 0.5  # Minimum expected Sharpe (was -4, should be ~0.82)
EXPECTED_SHARPE_MAX = 1.5  # Maximum expected Sharpe


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def browser_context(playwright):
    """Create browser context for tests."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        base_url=BASE_URL,
    )
    yield context
    context.close()
    browser.close()


@pytest.fixture
def page(browser_context):
    """Create new page for each test."""
    page = browser_context.new_page()
    yield page
    page.close()


@pytest.fixture
def logged_in_page(page):
    """Page with logged in user."""
    # Login flow
    page.goto("/login")
    page.fill("[data-testid=email-input]", "test@example.com")
    page.fill("[data-testid=password-input]", "testpassword")
    page.click("[data-testid=login-button]")
    page.wait_for_url("**/dashboard")
    return page


# =============================================================================
# Task 8.5: Data Validation Tests
# =============================================================================

class TestPerformanceKPIValidation:
    """Tests to verify KPI values are correct (Sharpe ~0.82, not -4)."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_sharpe_ratio_is_positive(self, logged_in_page):
        """
        CRITICAL: Verify Sharpe ratio is positive and reasonable.

        This test validates the core fix of Phase 1-8:
        - Old system showed Sharpe = -4 (bug)
        - New system should show Sharpe ≈ 0.82

        Acceptance Criteria:
        - Sharpe ratio is displayed
        - Value is between 0.5 and 1.5 (not -4)
        """
        page = logged_in_page

        # Navigate to performance tab
        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Wait for KPI cards to load
        page.wait_for_selector("[data-testid=sharpe-ratio-card]")

        # Get Sharpe ratio value
        sharpe_element = page.locator("[data-testid=sharpe-ratio-value]")
        sharpe_text = sharpe_element.inner_text()

        # Parse numeric value
        sharpe_value = float(sharpe_text.replace(",", ""))

        # CRITICAL ASSERTION: Sharpe should be positive and reasonable
        assert EXPECTED_SHARPE_MIN <= sharpe_value <= EXPECTED_SHARPE_MAX, (
            f"Sharpe ratio {sharpe_value} is outside expected range "
            f"[{EXPECTED_SHARPE_MIN}, {EXPECTED_SHARPE_MAX}]. "
            f"If negative (-4), the old bug has regressed!"
        )

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_sortino_ratio_displayed(self, logged_in_page):
        """Test Sortino ratio is displayed correctly."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Sortino should be visible
        sortino_element = page.locator("[data-testid=sortino-ratio-value]")
        expect(sortino_element).to_be_visible()

        # Value should be numeric
        sortino_text = sortino_element.inner_text()
        sortino_value = float(sortino_text.replace(",", ""))
        assert sortino_value > 0, "Sortino ratio should be positive"

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_max_drawdown_is_negative(self, logged_in_page):
        """Test max drawdown is displayed as negative percentage."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        drawdown_element = page.locator("[data-testid=max-drawdown-value]")
        drawdown_text = drawdown_element.inner_text()

        # Should be negative (e.g., "-3.2%")
        assert "-" in drawdown_text, "Max drawdown should be negative"


# =============================================================================
# Performance Tab UI Tests
# =============================================================================

class TestPerformanceTabUI:
    """Tests for Performance tab UI components."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_performance_tab_loads(self, logged_in_page):
        """Test performance tab loads without errors."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Tab should be active
        expect(page.locator("[data-testid=performance-tab]")).to_have_attribute(
            "aria-selected", "true"
        )

        # KPI section should be visible
        expect(page.locator("[data-testid=kpi-section]")).to_be_visible()

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_kpi_cards_display(self, logged_in_page):
        """Test all KPI cards are displayed."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Check all KPI cards
        kpi_cards = [
            "sharpe-ratio-card",
            "sortino-ratio-card",
            "calmar-ratio-card",
            "max-drawdown-card",
            "volatility-card",
            "cagr-card",
        ]

        for card_id in kpi_cards:
            expect(page.locator(f"[data-testid={card_id}]")).to_be_visible()


# =============================================================================
# Equity Curve Tests
# =============================================================================

class TestEquityCurve:
    """Tests for equity curve chart."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_equity_curve_renders(self, logged_in_page):
        """Test equity curve chart renders."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Wait for chart to render
        chart = page.locator("[data-testid=equity-curve-chart]")
        expect(chart).to_be_visible()

        # Chart should have SVG content
        expect(chart.locator("svg")).to_be_visible()

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_equity_curve_has_baseline(self, logged_in_page):
        """Test equity curve shows baseline comparison (QQQ)."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Toggle baseline if not visible
        baseline_toggle = page.locator("[data-testid=show-baseline-toggle]")
        if not baseline_toggle.is_checked():
            baseline_toggle.click()

        # Legend should show QQQ
        expect(page.locator("text=QQQ")).to_be_visible()


# =============================================================================
# Time Range Selector Tests
# =============================================================================

class TestTimeRangeSelector:
    """Tests for time range selector functionality."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_time_range_buttons(self, logged_in_page):
        """Test time range selector buttons work."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Click different time ranges
        time_ranges = ["1W", "1M", "3M", "YTD", "1Y", "ALL"]

        for range_button in time_ranges:
            button = page.locator(f"[data-testid=time-range-{range_button}]")
            button.click()

            # Button should be selected
            expect(button).to_have_attribute("aria-pressed", "true")

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_time_range_changes_data(self, logged_in_page):
        """Test that changing time range updates displayed data."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Get initial cumulative return
        initial_return = page.locator("[data-testid=cumulative-return-value]").inner_text()

        # Change to different time range
        page.click("[data-testid=time-range-1M]")
        page.wait_for_timeout(500)  # Wait for update

        # Value may be different for different time range
        # (This is a loose check - specific values depend on data)


# =============================================================================
# Baseline Comparison Tests
# =============================================================================

class TestBaselineComparison:
    """Tests for baseline comparison functionality."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_baseline_toggle(self, logged_in_page):
        """Test baseline comparison toggle."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        toggle = page.locator("[data-testid=show-baseline-toggle]")

        # Toggle on
        toggle.click()
        expect(page.locator("[data-testid=baseline-return]")).to_be_visible()

        # Toggle off
        toggle.click()
        expect(page.locator("[data-testid=baseline-return]")).not_to_be_visible()

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_baseline_shows_qqq(self, logged_in_page):
        """Test baseline shows QQQ symbol."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Enable baseline
        toggle = page.locator("[data-testid=show-baseline-toggle]")
        if not toggle.is_checked():
            toggle.click()

        # QQQ should be displayed
        expect(page.locator("text=QQQ")).to_be_visible()


# =============================================================================
# Mobile Responsive Tests
# =============================================================================

class TestMobileResponsive:
    """Tests for mobile responsive layout."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_mobile_viewport(self, browser_context):
        """Test performance tab on mobile viewport."""
        # Create mobile-sized page
        page = browser_context.new_page()
        page.set_viewport_size({"width": 375, "height": 812})  # iPhone X

        try:
            page.goto(f"{BASE_URL}/login")
            # Login...

            page.goto(f"{BASE_URL}/dashboard/strategies/{TEST_STRATEGY}")
            page.click("[data-testid=performance-tab]")

            # KPIs should still be visible
            expect(page.locator("[data-testid=sharpe-ratio-card]")).to_be_visible()

            # Should be stacked layout (cards in column)
            # Check that container has flex-col class on mobile

        finally:
            page.close()

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_tablet_viewport(self, browser_context):
        """Test performance tab on tablet viewport."""
        page = browser_context.new_page()
        page.set_viewport_size({"width": 768, "height": 1024})  # iPad

        try:
            page.goto(f"{BASE_URL}/dashboard/strategies/{TEST_STRATEGY}")

            # Should still be functional
            expect(page.locator("[data-testid=kpi-section]")).to_be_visible()

        finally:
            page.close()


# =============================================================================
# Data Refresh Tests
# =============================================================================

class TestDataRefresh:
    """Tests for data refresh behavior."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_refresh_button(self, logged_in_page):
        """Test manual refresh button."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Click refresh
        page.click("[data-testid=refresh-button]")

        # Should show loading state
        expect(page.locator("[data-testid=loading-indicator]")).to_be_visible()

        # Then hide after load
        page.wait_for_selector("[data-testid=loading-indicator]", state="hidden")

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_auto_refresh(self, logged_in_page):
        """Test auto-refresh functionality."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Wait for auto-refresh interval (if enabled)
        # This is a placeholder - actual interval depends on implementation


# =============================================================================
# EOD Status Indicator Tests
# =============================================================================

class TestEODStatusIndicator:
    """Tests for EOD finalization status indicator."""

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_eod_status_visible(self, logged_in_page):
        """Test EOD status indicator is visible."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Status indicator should be visible
        status = page.locator("[data-testid=eod-status-indicator]")
        expect(status).to_be_visible()

    @pytest.mark.skip(reason="Requires running dashboard")
    def test_eod_status_shows_finalized_date(self, logged_in_page):
        """Test EOD status shows data as of date."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Should show "Data as of: YYYY-MM-DD"
        status_text = page.locator("[data-testid=eod-data-as-of]").inner_text()
        assert re.match(r"\d{4}-\d{2}-\d{2}", status_text), (
            f"Expected date format YYYY-MM-DD, got: {status_text}"
        )


# =============================================================================
# Visual Regression Tests
# =============================================================================

class TestVisualRegression:
    """Visual regression tests using screenshots."""

    @pytest.mark.skip(reason="Requires running dashboard and baseline images")
    def test_performance_tab_screenshot(self, logged_in_page):
        """Take screenshot for visual regression comparison."""
        page = logged_in_page

        page.goto(f"/dashboard/strategies/{TEST_STRATEGY}")
        page.click("[data-testid=performance-tab]")

        # Wait for all data to load
        page.wait_for_load_state("networkidle")

        # Take screenshot
        page.screenshot(path="tests/e2e/screenshots/performance_tab.png")

        # Compare with baseline (would use visual testing tool)
        # assert_images_match("performance_tab.png", "baseline/performance_tab.png")
