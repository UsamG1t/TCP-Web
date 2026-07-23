/**
 * Application entry point.
 *
 * Loads the global stylesheet — which defines the design tokens every component
 * refers to — and mounts the root component into the placeholder in
 * `index.html`. Nothing else happens here; the app takes over from `App.svelte`.
 */

import "./app.css";
import App from "./App.svelte";

const app = new App({ target: document.getElementById("app") });
export default app;
