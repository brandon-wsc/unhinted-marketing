import path from "node:path";
import { defineConfig } from "vitest/config";
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
      // Single reserved API prefix (ADR 0006) — SPA owns all other paths.
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      include: [
        "src/lib/**",
        "src/features/session/session-storage.ts",
        "src/features/session/session-helpers.ts",
        "src/components/password-box.tsx",
        "src/components/user-menu-dropdown.tsx",
      ],
      exclude: [
        "src/lib/api.ts",
        "src/pages/**",
        "src/features/session/components/**",
        "src/main.tsx",
        "src/features/session/use-session.ts",
      ],
      thresholds: {
        "src/lib/**": { lines: 85 },
        "src/features/session/session-storage.ts": { lines: 85 },
        "src/features/session/session-helpers.ts": { lines: 85 },
        "src/components/password-box.tsx": { lines: 50 },
        "src/components/user-menu-dropdown.tsx": { lines: 50 },
      },
    },
  },
});
