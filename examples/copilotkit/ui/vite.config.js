import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The chat and everything Django serves are one origin as far as the
// browser is concerned, so session cookies flow and there is no CORS to
// configure: the AG-UI endpoints (`/agent/` and `/licence-agent/`), the
// wizards the handover links point at (`/quote/` and `/licence/`), and the
// fleet the person grows themselves (`/vehicles/`, and `/vehicle/` for the
// wizard behind each row).
const django = process.env.GANDALF_DJANGO_URL ?? "http://localhost:8100";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/agent": django,
      "/licence-agent": django,
      "/quote": django,
      "/licence": django,
      "/vehicles": django,
      "/vehicle": django,
    },
  },
});
