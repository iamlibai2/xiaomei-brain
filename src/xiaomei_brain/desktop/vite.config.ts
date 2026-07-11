import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  root: "renderer",
  base: "./",
  server: {
    watch: {
      usePolling: true,
      interval: 500,
    },
  },
  build: {
    outDir: "../dist/renderer",
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "renderer"),
    },
  },
});
