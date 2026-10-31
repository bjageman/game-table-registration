import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", ["PUBLIC_URL", "DEV_HOST"]);
  const publicHost = new URL(env.PUBLIC_URL || "http://localhost:5180")
    .hostname;
  return {
    plugins: [react()],
    server: {
      host: env.DEV_HOST || "127.0.0.1",
      port: 5180,
      strictPort: true,
      allowedHosts: [publicHost],
      proxy: { "/api": "http://127.0.0.1:8000" },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
