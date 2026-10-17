import { useEffect } from "react";

// Ctrl+S / Cmd+S calls `onSave` instead of the browser's save-page dialog.
export default function useSaveShortcut(onSave, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        onSave?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onSave, enabled]);
}
