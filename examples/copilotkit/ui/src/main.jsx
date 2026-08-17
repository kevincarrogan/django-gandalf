import React from "react";
import { createRoot } from "react-dom/client";

import Adaptive from "./Adaptive.jsx";
import App from "./App.jsx";
import Identity from "./Identity.jsx";
import Licence from "./Licence.jsx";

// Several demos, one dev server. A hash rather than a router: there are two
// pages and they share nothing but a layout, so a dependency to choose
// between them would be the largest thing on the page.
const PAGES = { licence: Licence, identity: Identity, adaptive: Adaptive };

// Normalised rather than matched literally: `#identity`, `#identity/` and
// `#Identity` are the same request as far as anybody typing one is
// concerned, and an exact match sends the second two to the wrong demo
// without saying why.
function current() {
  const name = window.location.hash
    .replace(/^#/, "")
    .replace(/\/+$/, "")
    .toLowerCase();
  const Page = PAGES[name];
  return Page ? <Page /> : <App />;
}

const root = createRoot(document.getElementById("root"));

function render() {
  root.render(<React.StrictMode>{current()}</React.StrictMode>);
}

window.addEventListener("hashchange", render);
render();
