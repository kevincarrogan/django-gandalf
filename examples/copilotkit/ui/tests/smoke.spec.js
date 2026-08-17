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
    // The greeting rather than the panel heading: it is the thing that
    // has to be in the conversation before anybody types, and it is what
    // tells them that asking for a form is an option.
    mounted: (page) => page.getByText("I can sort out a business insurance quote"),
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

// The regression this exists for: an opener sent the message by calling
// `agent.runAgent()` on the agent itself, which posts `tools: []`. The
// frontend tools a page registers are attached by the *core*, so the model
// was never told it could draw a form and described one in prose instead —
// which is indistinguishable from it deciding not to draw one, and reads as
// the model being unhelpful rather than the page being wrong.
//
// What is asserted is the request rather than a rendered form, and that is
// a concession to the canned model rather than a preference. `TestModel`
// calls every tool it is offered, but only from a conversation it has not
// already spoken in — and this page greets you, so by the time an opener is
// clicked there is an assistant turn in the history and it calls nothing at
// all. Against a real model the greeting changes nothing: both draw a form,
// through the same three tools. So the form is checked by hand and by
// `just test-ui` against a key, and what runs in CI for free is the half
// that actually broke.
test("the adaptive quote's openers reach the model with its tools", async ({ page }) => {
  let sentTools = null;
  await page.route("**/adaptive-agent/", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}");
    sentTools = (body.tools ?? []).map((tool) => tool.name);
    await route.continue();
  });

  await page.goto("/#adaptive");
  await page.getByRole("button", { name: /never bought insurance/ }).click();

  await expect
    .poll(() => sentTools, { timeout: 20_000 })
    .toContain("collect_with_a_form");
});
