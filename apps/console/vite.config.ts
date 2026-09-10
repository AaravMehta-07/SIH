import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: the console talks to the local FORESIGHT API
// (python scripts/serve_console.py on 127.0.0.1:8001).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8001",
      "/health": "http://127.0.0.1:8001",
    },
  },
});
