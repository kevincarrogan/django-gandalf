// CopilotKit ships a dev inspector and turns it on for anything served
// from localhost, which is everything here. It is worth having while
// building — but not in a test run, where it floats a button over the
// page's own controls at the highest z-index there is, and fetches its
// announcements from a CDN, which makes an otherwise self-contained suite
// depend on somebody else's uptime.
//
// So the browser tests start Vite with `VITE_COPILOT_INSPECTOR=off` (see
// `playwright.config.js`) and the demo you run by hand is untouched.
export const inspectorEnabled = import.meta.env.VITE_COPILOT_INSPECTOR !== "off";
