import fs from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const certDir = path.resolve(import.meta.dirname, "./certs");
const certFile = path.join(certDir, "unhinted.localhost.pem");
const keyFile = path.join(certDir, "unhinted.localhost-key.pem");
const https =
  fs.existsSync(certFile) && fs.existsSync(keyFile)
    ? { cert: fs.readFileSync(certFile), key: fs.readFileSync(keyFile) }
    : undefined;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  server: {
    port: 5173,
    // Instagram Login callback is `{WEB_BASE_URL}/api/social/oauth/callback`.
    // Fail instead of hopping to 5174 when 5173 is taken.
    strictPort: true,
    https,
    // Instagram Login needs a stable HTTPS origin; enable TLS when web/certs pems exist.
    allowedHosts: ["unhinted.localhost", "localhost"],
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
        "src/features/session/session-layout.ts",
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
        "src/features/session/session-layout.ts": { lines: 85 },
        "src/components/password-box.tsx": { lines: 50 },
        "src/components/user-menu-dropdown.tsx": { lines: 50 },
      },
    },
  },
});
