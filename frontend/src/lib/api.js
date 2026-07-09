// Thin client for the simulator backend.
// In dev the backend runs on :5000; override with VITE_API_BASE if needed.
// Behind nginx in production, set VITE_API_BASE="" (same origin).

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:5000";

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

// Fresh run.
export function runSimulation({ config, duration, seed }) {
  return post("/simulate", { config, duration, seed });
}

// Continue from a previous checkpoint, optionally with new params.
export function continueSimulation({ config, duration, resumeState }) {
  return post("/simulate", { config, duration, resume_state: resumeState });
}
