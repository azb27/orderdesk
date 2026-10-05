import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against a running stack (API + built UI on one port), e.g. `make e2e`.
// Run without ANTHROPIC_API_KEY so orders are read by the deterministic fallback parser.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1500, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
});
