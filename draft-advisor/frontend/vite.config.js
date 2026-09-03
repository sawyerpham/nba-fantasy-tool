import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on 8000 (python -m app.serve); the dev server proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
