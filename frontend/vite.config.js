import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on 8000 (python -m app.serve); the dev server proxies /api to it.
// Override with DA_API_TARGET (e.g. http://127.0.0.1:8001) when running a second backend.
const target = process.env.DA_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target, changeOrigin: true },
    },
  },
});
