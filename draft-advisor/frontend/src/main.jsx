import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// Number fields select their contents on focus so a click-and-type replaces the value.
document.addEventListener("focusin", (e) => {
  if (e.target instanceof HTMLInputElement && e.target.type === "number") e.target.select();
});

createRoot(document.getElementById("root")).render(<App />);
