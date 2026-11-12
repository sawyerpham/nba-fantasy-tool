import React from "react";
import { createRoot } from "react-dom/client";

// Number fields select their contents on focus so a click-and-type replaces the value.
document.addEventListener("focusin", (e) => {
  if (e.target instanceof HTMLInputElement && e.target.type === "number") e.target.select();
});

// Settings > Appearance > UI (core/Shell.jsx UIS): "command" / "broadcast" load the redesigns (src/ui-*, their stylesheets
// build on styles.css), else the default UI. Only one UI's App and global stylesheet load per page, so switching reloads the page.
const LOADERS = {
  command: () => [import("./ui-command/App.jsx"), import("./ui-command/command.css")],
  broadcast: () => [import("./ui-broadcast/App.jsx"), import("./ui-broadcast/broadcast.css")],
};
const ui = (() => { try { return localStorage.getItem("da.ui") || ""; } catch { return ""; } })();
Promise.all((LOADERS[ui] || (() => [import("./App.jsx"), import("./styles.css")]))())
  .then(([{ default: App }]) => createRoot(document.getElementById("root")).render(<App />));
