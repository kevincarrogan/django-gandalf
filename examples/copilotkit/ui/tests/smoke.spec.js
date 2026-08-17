import { expect, test as base } from "@playwright/test";

// What `npm run build` cannot see, in a browser that can: whether each
// page mounts, whether it threw on the way, whether the composer's attach
// path still works, and whether the dev server is still proxying Django.
//
// Every failure this file exists for shipped past a green build in one
// afternoon (#81) — an import trimmed with the code that used it, JSX with
// no React import, an inert attach button, a lost proxy. None of them is a
// syntax error, and three of the four render a blank page.

// With the inspector off (see `src/inspector.js`) these pages make no
// requests at all beyond localhost, so anything else on the console came
// from a third party — and only when this suite is run against a demo
// somebody already had up, which keeps its inspector. A failure to reach
// somebody else's CDN is not this demo being broken.
const ours = (url) => !/^https?:\/\//.test(url) || url.startsWith("http://localhost:");

// Attached to every test rather than asked for, because the failures worth
// catching arrive as console noise rather than as a failed assertion: a
// page that renders nothing passes any check you did not think to write.
const test = base.extend({
  problems: [
    async ({ page }, use) => {
      const problems = [];
      page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error" && ours(message.location().url)) {
          problems.push(`console: ${message.text()}`);
        }
      });
      await use(problems);
      expect(problems, "the browser reported errors").toEqual([]);
    },
    { auto: true },
  ],
});

// One page per route `main.jsx` knows about, and something on each that is
// only there if React got as far as rendering it.
const PAGES = [
  {
    name: "the insurance quote demo",
    path: "/",
    mounted: (page) =>
      page.getByRole("heading", { name: "Business insurance quote" }),
  },
  {
    name: "the adaptive quote",
    path: "/#adaptive",
    mounted: (page) =>
      page.getByRole("heading", { name: "A copilot that draws its own forms" }),
  },
  {
    name: "the driving licence check",
    path: "/#licence",
    mounted: (page) => page.getByText("I can check a driving licence for you"),
    panel: "Driving licence check",
  },
  {
    name: "the identity check",
    path: "/#identity",
    mounted: (page) => page.getByText("I can confirm your identity for you"),
    panel: "Identity check",
  },
];

for (const { name, path, mounted } of PAGES) {
  test(`${name} renders`, async ({ page }) => {
    await page.goto(path);

    await expect(mounted(page)).toBeVisible();
    // The chat is the demo. A panel without one is a page that half
    // mounted, which is what a throw inside CopilotKit looks like.
    await expect(page.getByRole("textbox")).toBeVisible();
  });
}

// The panels are behind the toggle because they are instrumentation, which
// also means nothing else here would notice if one started throwing.
for (const { name, path, panel } of PAGES.filter((p) => p.panel)) {
  test(`${name} opens its run details`, async ({ page }) => {
    await page.goto(path);
    await page.getByRole("button", { name: "Run details" }).click();

    await expect(page.getByRole("heading", { name: panel })).toBeVisible();
  });
}

// The regression this replaces: `attachments` was switched off, and
// CopilotKit's attach button went on rendering — enabled, and inert. Only
// using it says whether it works, so this uses it.
for (const { name, path } of PAGES.filter((p) => p.panel)) {
  test(`${name} can attach a photo`, async ({ page }) => {
    await page.goto(path);
    await page.getByTestId("copilot-add-menu-button").click();

    const [chooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByRole("menuitem", { name: "Add attachments" }).click(),
    ]);
    expect(chooser.isMultiple()).toBe(true);
  });
}

test("the dev server is still proxying Django", async ({ request }) => {
  // A GET is no use here: Vite answers anything it does not recognise with
  // index.html and a 200, so a missing proxy reads as a working page. A
  // POST to the same path 404s, which is how the chat found out.
  for (const endpoint of [
    "/agent/",
    "/adaptive-agent/",
    "/licence-agent/",
    "/identity-agent/",
  ]) {
    const response = await request.post(endpoint, { failOnStatusCode: false });
    expect(response.status(), `POST ${endpoint}`).not.toBe(404);
  }

  // And the wizard's own URL, which Django answers with a redirect to the
  // first step. Vite's fallback would answer 200 with the chat in it.
  const wizard = await request.get("/quote/", { maxRedirects: 0 });
  expect(wizard.status(), "GET /quote/").toBe(302);
});
