import { fileURLToPath } from "node:url";
import { satteri } from "@astrojs/markdown-satteri";
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";
import { repoLinks } from "./src/lib/repo-links.ts";

// https://astro.build/config
export default defineConfig({
  markdown: {
    processor: satteri({
      hastPlugins: [repoLinks(fileURLToPath(new URL("..", import.meta.url)))],
    }),
  },
  vite: {
    plugins: [tailwindcss()],
  },
  security: {
    checkOrigin: false,
  },
});
