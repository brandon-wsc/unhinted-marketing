import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/auth": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
      "/sessions": { target: "http://localhost:8000", changeOrigin: true },
      "/companies": { target: "http://localhost:8000", changeOrigin: true },
      "/signals": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
