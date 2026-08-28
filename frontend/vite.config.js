import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Build straight into ../web so every existing URL keeps working:
//   god UI     -> http://localhost:8788/            (serves web/god.html)
//   replay     -> web/viewer.html                   (served by 8787 or /static)
// Committed build output = judges need no npm install.
// dev で "/" を神モード(god.html)へ（ビルド成果物と同じ導線にする）
const rootToGod = {
  name: "root-to-god",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url === "/" || req.url === "/index.html") req.url = "/god.html";
      next();
    });
  },
};

export default defineConfig({
  plugins: [react(), rootToGod],
  base: "./",   // 相対パス → 8788の"/"でも 8787の"/web/"でも配信できる
  server: {
    proxy: {
      "/api": "http://localhost:8788",
      "/static": "http://localhost:8788",
      "/world.geojson": {
        target: "http://localhost:8788",
        rewrite: () => "/static/web/world.geojson",
      },
      "/ws": { target: "ws://localhost:8788", ws: true },
    },
  },
  build: {
    outDir: resolve(__dirname, "../web"),
    emptyOutDir: false,          // keep world.geojson etc. in web/
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/chunk-[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
