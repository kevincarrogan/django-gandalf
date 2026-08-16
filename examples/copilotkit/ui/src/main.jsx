import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import Identity from "./Identity.jsx";
import Licence from "./Licence.jsx";

// Two demos, one dev server. A hash rather than a router: there are two
// pages and they share nothing but a layout, so a dependency to choose
// between them would be the largest thing on the page.
const PAGES = { "#licence": Licence, "#identity": Identity };

function current() {
  const Page = PAGES[window.location.hash];
  return Page ? <Page /> : <App />;
}

const root = createRoot(document.getElementById("root"));

function render() {
  root.render(<React.StrictMode>{current()}</React.StrictMode>);
}

window.addEventListener("hashchange", render);
render();
