import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      // The API is a separate service. Proxying in dev means the browser only ever
      // talks to one origin, so there is no CORS dance in the common path.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { target: "es2022", chunkSizeWarningLimit: 900 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
