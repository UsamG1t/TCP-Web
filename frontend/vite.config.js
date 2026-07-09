import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// base is '/' in dev; the production image sets VITE_BASE=/latest/ so assets
// resolve when the app is served under http://HOST/latest/.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [svelte()],
  server: {
    port: 5173,
  },
});
