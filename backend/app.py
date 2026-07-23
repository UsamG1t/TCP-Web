"""HTTP API for the simulator.

A thin layer over `engine.simulate()`: it validates input, calls the engine, and
returns JSON. All the interesting behaviour lives in `engine`; nothing here
knows anything about TCP.

The service is **stateless**. There are no sessions and no run identifiers: to
continue a simulation the client sends back the checkpoint it received earlier,
together with the parameters to continue under. Any instance can serve any
request, and restarting the process loses nothing.

Endpoints:

- `GET /health` — liveness probe.
- `GET /schema` — parameter defaults and ranges, used to build the client form.
- `POST /simulate` — run or continue a simulation.

Cross-origin requests are enabled because in development the frontend is served
by Vite on a different port than this API.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS

from engine.config import schema, validate_config, DURATION_MIN, DURATION_MAX
from engine.core import simulate

app = Flask(__name__)
CORS(app)

MAX_EVENTS = 200_000
"""Largest trace the API will return.

A long run at a high bandwidth can generate an enormous number of events; this
cap keeps a single request from producing a response no client could reasonably
handle. Exceeding it yields HTTP 413.
"""


@app.get("/health")
def health():
    """Report that the service is up. Returns `{"status": "ok"}`."""
    return jsonify({"status": "ok"})


@app.get("/schema")
def get_schema():
    """Return the parameter schema: defaults, ranges, protocols, modes.

    The frontend builds its form from this response and validates locally
    against the same bounds the server enforces.
    """
    return jsonify(schema())


@app.post("/simulate")
def post_simulate():
    """Run a simulation, or continue one, and return the resulting trace.

    Request body fields, all optional:

    - `config` — simulation parameters; anything omitted takes its default.
    - `duration` — seconds of virtual time to simulate (default 30).
    - `seed` — seed for reproducible loss decisions (default 1).
    - `resume_state` — a `checkpoint` from an earlier response, to continue that
      run instead of starting a new one.

    Responds with `events`, `checkpoint` and `stats`.

    Every field is validated before the engine is touched. `duration` and `seed`
    reject booleans explicitly, since Python would otherwise accept `True` as
    the number 1 and silently simulate something the client did not ask for.
    A malformed `resume_state` cannot be validated field by field, so the engine
    call is guarded and any failure reported as a bad request rather than a
    server error.

    Status codes: 200 on success, 400 for invalid input or an unusable
    checkpoint, 413 when the trace would exceed `MAX_EVENTS`.
    """
    body = request.get_json(silent=True) or {}

    try:
        cfg = validate_config(body.get("config", {}))
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400

    duration = body.get("duration", 30)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) \
            or not (DURATION_MIN <= duration <= DURATION_MAX):
        return jsonify({"error": f"duration must be between {DURATION_MIN} and {DURATION_MAX}"}), 400

    seed = body.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int):
        return jsonify({"error": "seed must be an integer"}), 400

    resume = body.get("resume_state")
    if resume is not None and not isinstance(resume, dict):
        return jsonify({"error": "resume_state must be an object"}), 400

    try:
        result = simulate(cfg, int(duration), seed=seed, resume_state=resume)
    except Exception as ex:
        return jsonify({"error": "simulation failed", "detail": str(ex)}), 400

    if len(result["events"]) > MAX_EVENTS:
        return jsonify({"error": "trace too large; reduce duration or bandwidth"}), 413

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
