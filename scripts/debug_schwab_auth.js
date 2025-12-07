/**
 * Playwright Script: Debug Schwab Auth UI Issue
 *
 * Tests both local and Docker deployments to collect evidence:
 * - Network requests to /api/schwab/status
 * - Browser console errors
 * - HTTP status codes and response bodies
 * - Authorization header presence
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// Test configurations
const TESTS = [
  {
    name: 'Local Deployment',
    url: 'http://localhost:3000/config',
    description: 'Testing local development server'
  },
  {
    name: 'Docker Deployment',
    url: 'http://192.168.7.100:8787/config',
    description: 'Testing Docker deployment on Unraid'
  }
];

// Evidence collection
const evidence = {
  timestamp: new Date().toISOString(),
  tests: []
};

async function testDeployment(config) {
  console.log(`\n${'='.repeat(80)}`);
  console.log(`Testing: ${config.name}`);
  console.log(`URL: ${config.url}`);
  console.log(`${'='.repeat(80)}\n`);

  const testResult = {
    name: config.name,
    url: config.url,
    timestamp: new Date().toISOString(),
    consoleMessages: [],
    networkRequests: [],
    errors: [],
    screenshots: {}
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
  });
  const page = await context.newPage();

  // Capture console messages
  page.on('console', msg => {
    const entry = {
      type: msg.type(),
      text: msg.text(),
      location: msg.location()
    };
    testResult.consoleMessages.push(entry);
    console.log(`[CONSOLE ${msg.type().toUpperCase()}] ${msg.text()}`);
  });

  // Capture all network requests
  page.on('request', request => {
    if (request.url().includes('/api/schwab')) {
      const headers = request.headers();
      console.log(`\n[REQUEST] ${request.method()} ${request.url()}`);
      console.log(`  Authorization: ${headers.authorization || 'NOT SET'}`);
      console.log(`  Headers:`, JSON.stringify(headers, null, 2));
    }
  });

  // Capture all network responses
  page.on('response', async response => {
    if (response.url().includes('/api/schwab')) {
      const requestHeaders = response.request().headers();
      let responseBody = null;
      let responseText = null;

      try {
        responseText = await response.text();
        responseBody = JSON.parse(responseText);
      } catch (e) {
        responseBody = { error: 'Failed to parse JSON', raw: responseText };
      }

      const networkEntry = {
        method: response.request().method(),
        url: response.url(),
        status: response.status(),
        statusText: response.statusText(),
        requestHeaders: requestHeaders,
        responseHeaders: response.headers(),
        responseBody: responseBody
      };

      testResult.networkRequests.push(networkEntry);

      console.log(`\n[RESPONSE] ${response.status()} ${response.url()}`);
      console.log(`  Status: ${response.status()} ${response.statusText()}`);
      console.log(`  Authorization Header Sent: ${requestHeaders.authorization ? 'YES' : 'NO'}`);
      console.log(`  Response Body:`, JSON.stringify(responseBody, null, 2));
    }
  });

  try {
    // Navigate to config page
    console.log('\n[ACTION] Navigating to config page...');
    const response = await page.goto(config.url, {
      waitUntil: 'networkidle',
      timeout: 30000
    });

    if (!response) {
      throw new Error('Failed to load page - no response');
    }

    console.log(`[PAGE LOAD] Status: ${response.status()}`);
    testResult.pageLoadStatus = response.status();

    // Take screenshot after initial load
    const screenshotPath = path.join(__dirname, `debug_${config.name.replace(/\s+/g, '_')}_initial.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    testResult.screenshots.initial = screenshotPath;
    console.log(`[SCREENSHOT] Saved to ${screenshotPath}`);

    // Wait for Schwab Auth component to load
    console.log('\n[ACTION] Waiting for Schwab Auth component...');
    try {
      await page.waitForSelector('text=Schwab API Authentication', { timeout: 10000 });
      console.log('[SUCCESS] Schwab Auth component found');
    } catch (e) {
      console.log('[ERROR] Schwab Auth component not found within 10s');
      testResult.errors.push('Schwab Auth component not found');
    }

    // Wait a bit for API calls to complete
    await page.waitForTimeout(3000);

    // Check for error messages in the UI
    console.log('\n[ACTION] Checking for error messages in UI...');
    const errorElement = await page.locator('text=Failed to load authentication status').first();
    const errorVisible = await errorElement.isVisible().catch(() => false);

    if (errorVisible) {
      console.log('[FOUND] Error message visible in UI: "Failed to load authentication status"');
      testResult.errors.push('UI shows: Failed to load authentication status');

      // Take screenshot of error
      const errorScreenshotPath = path.join(__dirname, `debug_${config.name.replace(/\s+/g, '_')}_error.png`);
      await page.screenshot({ path: errorScreenshotPath, fullPage: true });
      testResult.screenshots.error = errorScreenshotPath;
      console.log(`[SCREENSHOT] Error state saved to ${errorScreenshotPath}`);
    } else {
      console.log('[INFO] No error message found in UI');
    }

    // Check localStorage for token
    const token = await page.evaluate(() => localStorage.getItem('jutsu_auth_token'));
    testResult.hasToken = !!token;
    console.log(`\n[TOKEN] JWT Token in localStorage: ${token ? 'YES' : 'NO'}`);
    if (token) {
      console.log(`[TOKEN] Token preview: ${token.substring(0, 50)}...`);
    }

    // Check if AUTH_REQUIRED is enabled by looking at the page
    const loginVisible = await page.locator('text=Login').first().isVisible().catch(() => false);
    testResult.authRequired = loginVisible;
    console.log(`[AUTH] Login prompt visible: ${loginVisible ? 'YES (AUTH_REQUIRED=true)' : 'NO (AUTH_REQUIRED=false)'}`);

  } catch (error) {
    console.error(`\n[FATAL ERROR] ${error.message}`);
    testResult.errors.push(`Fatal: ${error.message}`);

    // Take screenshot of error state
    const errorScreenshotPath = path.join(__dirname, `debug_${config.name.replace(/\s+/g, '_')}_fatal.png`);
    await page.screenshot({ path: errorScreenshotPath, fullPage: true });
    testResult.screenshots.fatal = errorScreenshotPath;
  } finally {
    await browser.close();
  }

  evidence.tests.push(testResult);
  return testResult;
}

async function analyzeEvidence() {
  console.log(`\n${'='.repeat(80)}`);
  console.log('EVIDENCE ANALYSIS');
  console.log(`${'='.repeat(80)}\n`);

  for (const test of evidence.tests) {
    console.log(`\n${test.name}:`);
    console.log(`  URL: ${test.url}`);
    console.log(`  Has Token: ${test.hasToken}`);
    console.log(`  Auth Required: ${test.authRequired}`);
    console.log(`  Page Load Status: ${test.pageLoadStatus || 'N/A'}`);
    console.log(`  Network Requests: ${test.networkRequests.length}`);
    console.log(`  Console Messages: ${test.consoleMessages.length}`);
    console.log(`  Errors: ${test.errors.length}`);

    // Analyze Schwab API requests
    const schwabRequests = test.networkRequests.filter(r => r.url.includes('/api/schwab/status'));

    if (schwabRequests.length > 0) {
      console.log(`\n  Schwab API Requests (${schwabRequests.length}):`);
      schwabRequests.forEach((req, idx) => {
        console.log(`    Request ${idx + 1}:`);
        console.log(`      Method: ${req.method}`);
        console.log(`      URL: ${req.url}`);
        console.log(`      Status: ${req.status} ${req.statusText}`);
        console.log(`      Authorization Header: ${req.requestHeaders.authorization ? 'PRESENT' : 'MISSING'}`);
        console.log(`      Response:`, JSON.stringify(req.responseBody, null, 8));
      });
    } else {
      console.log(`\n  NO Schwab API requests captured`);
    }

    // Show errors
    if (test.errors.length > 0) {
      console.log(`\n  Errors:`);
      test.errors.forEach(err => console.log(`    - ${err}`));
    }

    // Show console errors
    const consoleErrors = test.consoleMessages.filter(m => m.type === 'error');
    if (consoleErrors.length > 0) {
      console.log(`\n  Console Errors:`);
      consoleErrors.forEach(err => console.log(`    - ${err.text}`));
    }
  }

  // Save evidence to file
  const evidencePath = path.join(__dirname, 'schwab_auth_evidence.json');
  fs.writeFileSync(evidencePath, JSON.stringify(evidence, null, 2));
  console.log(`\n[SAVED] Evidence saved to ${evidencePath}`);
}

async function main() {
  console.log('Schwab Auth Debug Test');
  console.log('======================\n');
  console.log(`Testing ${TESTS.length} deployments...`);

  for (const config of TESTS) {
    try {
      await testDeployment(config);
    } catch (error) {
      console.error(`Failed to test ${config.name}:`, error);
      evidence.tests.push({
        name: config.name,
        url: config.url,
        errors: [`Failed to run test: ${error.message}`]
      });
    }
  }

  await analyzeEvidence();

  console.log('\n' + '='.repeat(80));
  console.log('TEST COMPLETE');
  console.log('='.repeat(80));
}

main().catch(console.error);
