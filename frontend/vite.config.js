import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Build straight into ../web so every existing URL keeps working:
//   god UI     -> http://localhost:8788/            (serves web/god.html)
//   replay     -> web/viewer.html                   (served by 8787 or /static)
// Committed build output = judges need no npm install.
export default defineConfig({
  plugins: [react()],
  base: "./",   // 相対パス → 8788の"/"でも 8787の"/web/"でも配信できる
  build: {
    outDir: resolve(__dirname, "../web"),
    emptyOutDir: false,          // keep world.geojson etc. in web/
    rollupOptions: {
      input: {
        god: resolve(__dirname, "god.html"),
        viewer: resolve(__dirname, "viewer.html"),
      },
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/chunk-[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
