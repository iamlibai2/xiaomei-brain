import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "path";

const PDF_ASSET_DIRECTORIES = ["cmaps", "standard_fonts", "wasm", "iccs"];

function copyPdfAssets(pdfRoot: string): Plugin {
  return {
    name: "copy-pdfjs-assets",
    writeBundle() {
      const outputRoot = path.resolve(__dirname, "dist/renderer/pdfjs");
      for (const directory of PDF_ASSET_DIRECTORIES) {
        fs.cpSync(
          path.join(pdfRoot, directory),
          path.join(outputRoot, directory),
          { recursive: true },
        );
      }
    },
  };
}

export default defineConfig(({ command }) => {
  const pdfRoot = path.resolve(__dirname, "node_modules/pdfjs-dist");
  const developmentAssetBase = `/@fs/${pdfRoot.replace(/\\/g, "/")}/`;
  return {
    plugins: [react(), copyPdfAssets(pdfRoot)],
    root: "renderer",
    base: "./",
    define: {
      __PDFJS_ASSET_BASE__: JSON.stringify(
        command === "serve" ? developmentAssetBase : "./pdfjs/",
      ),
    },
    server: {
      fs: {
        allow: [path.resolve(__dirname), pdfRoot],
      },
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
  };
});
