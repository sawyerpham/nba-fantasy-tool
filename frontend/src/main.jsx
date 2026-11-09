import React from "react";
import { createRoot } from "react-dom/client";

// Number fields select their contents on focus so a click-and-type replaces the value.
document.addEventListener("focusin", (e) => {
  if (e.target instanceof HTMLInputElement && e.target.type === "number") e.target.select();
});

// Settings > Appearance > UI: "classic" loads the pre-makeover backup (src/classic, frozen: don't edit it), else the
// current UI. Only one UI's App and global stylesheet load per page, so switching reloads the page.
const classic = (() => { try { return localStorage.getItem("da.ui") === "classic"; } catch { return false; } })();
Promise.all(classic
  ? [import("./classic/App.jsx"), import("./classic/styles.css")]
  : [import("./App.jsx"), import("./styles.css")])
  .then(([{ default: App }]) => createRoot(document.getElementById("root")).render(<App />));
