import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import Licence from "./Licence.jsx";

// Two demos, one dev server. A hash rather than a router: there are two
// pages and they share nothing but a layout, so a dependency to choose
// between them would be the largest thing on the page.
function current() {
  return window.location.hash === "#licence" ? <Licence /> : <App />;
}

const root = createRoot(document.getElementById("root"));

function render() {
  root.render(<React.StrictMode>{current()}</React.StrictMode>);
}

window.addEventListener("hashchange", render);
render();
