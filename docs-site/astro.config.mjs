import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  // Documentação interna: sem domínio de produção definido ainda.
  site: "http://localhost:4321",
  output: "static",
  integrations: [sitemap()],
  vite: { plugins: [tailwindcss()] },
});
