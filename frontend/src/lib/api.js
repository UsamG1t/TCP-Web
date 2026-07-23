/**
 * Client for the simulator's REST API.
 *
 * Three calls, all thin: fetch the parameter schema, run a simulation, continue
 * one. Everything else the UI does happens locally on the returned trace.
 *
 * The base URL is configurable because the frontend runs in two quite different
 * places. In development Vite serves it on port 5173 while the API is on 5000,
 * so requests are cross-origin and need an absolute URL. In production both are
 * behind the same nginx, so `VITE_API_BASE` is set to `/api` at build time and
 * requests become same-origin.
 *
 * Network failures are translated into a message worth showing a user, because
 * the overwhelmingly likely cause in development is simply that the backend is
 * not running — a bare `TypeError: Failed to fetch` would not say so.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:5000";

/**
 * POST a JSON body to the API and return the parsed response.
 *
 * @param {string} path Path appended to the configured base URL.
 * @param {Object} body Request body, serialised as JSON.
 * @returns {Promise<Object>} The parsed response body.
 * @throws {Error} If the backend is unreachable, or replies with an error
 *   status. The API's own `error` message is preferred when present, since it
 *   explains which parameter was rejected and why.
 */
async function post(path, body) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("Can't reach the simulator. Is the backend running on :5000?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/**
 * Fetch the parameter schema used to build the configuration form.
 *
 * Requested once at start-up. Taking defaults and bounds from the server keeps
 * the form in step with what the backend will actually accept, instead of
 * duplicating the limits in the UI.
 *
 * @returns {Promise<Object>} Numeric parameters with their defaults and ranges,
 *   the available protocols and retransmission modes, and the duration limits.
 * @throws {Error} If the backend is unreachable or replies with an error status.
 */
export async function getSchema() {
  let res;
  try {
    res = await fetch(`${BASE}/schema`);
  } catch (e) {
    throw new Error("Can't reach the simulator. Is the backend running on :5000?");
  }
  if (!res.ok) throw new Error(`Couldn't load parameters (${res.status})`);
  return res.json();
}

/**
 * Run a new simulation from time zero.
 *
 * @param {Object} params Request parameters.
 * @param {Object} params.config Simulation parameters from the form.
 * @param {number} params.duration Seconds of virtual time to simulate.
 * @param {number} params.seed Seed for reproducible loss decisions.
 * @returns {Promise<Object>} The trace (`events`), a `checkpoint` for
 *   continuing, and summary `stats`.
 */
export function runSimulation({ config, duration, seed }) {
  return post("/simulate", { config, duration, seed });
}

/**
 * Extend an existing run, optionally under different parameters.
 *
 * The checkpoint carries everything needed to resume, so the server keeps no
 * state between the two calls. Passing a modified `config` is what lets the user
 * change protocol or loss rate partway through and watch the sender react;
 * segments already in flight keep the fate they were given.
 *
 * @param {Object} params Request parameters.
 * @param {Object} params.config Parameters for the continuation.
 * @param {number} params.duration Additional seconds of virtual time.
 * @param {Object} params.resumeState The `checkpoint` from the previous response.
 * @returns {Promise<Object>} Only the new events, plus an updated checkpoint and
 *   cumulative stats. The caller appends them to the existing trace.
 */
export function continueSimulation({ config, duration, resumeState }) {
  return post("/simulate", { config, duration, resume_state: resumeState });
}
