import { defineConfig } from "@playwright/test";

// The demo's own two-terminal recipe, started for you. `reuseExistingServer`
// means running these while you already have the demo up costs nothing and
// tests what you are looking at; without it, the ports would collide.
const djangoPort = process.env.GANDALF_DJANGO_PORT ?? "8100";
const django = `http://localhost:${djangoPort}`;
const ui = "http://localhost:5173";

export default defineConfig({
  testDir: "./tests",
  // A failure in CI is a page nobody can look at, so it keeps a trace and
  // a screenshot of the moment. Locally they cost nothing: passing runs
  // write neither.
  use: {
    baseURL: ui,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // No retries. These catch a page that fails to mount, and a mount that
  // only fails sometimes is the most interesting result this suite can
  // produce — retrying it away would be the one thing not to do.
  retries: 0,
  webServer: [
    {
      // Migrates before it serves, so a fresh checkout works.
      command: `just copilotkit-server ${djangoPort}`,
      cwd: "../../..",
      url: `${django}/quote/`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      // `--strictPort`, so a busy 5173 fails here rather than moving the
      // dev server to 5174 and leaving the tests to smoke-test whatever
      // was already on 5173.
      command: "npm run dev -- --port 5173 --strictPort",
      // The inspector is CopilotKit's, useful, and not under test — see
      // `src/inspector.js`. Note that `reuseExistingServer` means a demo
      // you already had running keeps it, so nothing here may depend on
      // it being gone.
      env: { GANDALF_DJANGO_URL: django, VITE_COPILOT_INSPECTOR: "off" },
      url: ui,
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
