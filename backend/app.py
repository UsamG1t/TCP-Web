"""Flask API for the TCP simulator.

Endpoints:
  GET  /health    -> liveness probe
  GET  /schema    -> defaults, ranges, protocols (drives the frontend form)
  POST /simulate  -> run (or continue) a simulation, return events + checkpoint

The backend is stateless: to "continue" a run, the client sends back the
checkpoint it received earlier, together with the (possibly new) config.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS

from engine.config import schema, validate_config, DURATION_MIN, DURATION_MAX
from engine.core import simulate

app = Flask(__name__)
CORS(app)

# Safety cap: reject requests that would generate an unreasonable trace.
MAX_EVENTS = 200_000


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/schema")
def get_schema():
    return jsonify(schema())


@app.post("/simulate")
def post_simulate():
    body = request.get_json(silent=True) or {}

    # config
    try:
        cfg = validate_config(body.get("config", {}))
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400

    # duration
    duration = body.get("duration", 30)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) \
            or not (DURATION_MIN <= duration <= DURATION_MAX):
        return jsonify({"error": f"duration must be between {DURATION_MIN} and {DURATION_MAX}"}), 400

    # seed
    seed = body.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int):
        return jsonify({"error": "seed must be an integer"}), 400

    # resume_state (optional, comes from a previous checkpoint)
    resume = body.get("resume_state")
    if resume is not None and not isinstance(resume, dict):
        return jsonify({"error": "resume_state must be an object"}), 400

    try:
        result = simulate(cfg, int(duration), seed=seed, resume_state=resume)
    except Exception as ex:  # malformed checkpoint, etc.
        return jsonify({"error": "simulation failed", "detail": str(ex)}), 400

    if len(result["events"]) > MAX_EVENTS:
        return jsonify({"error": "trace too large; reduce duration or bandwidth"}), 413

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
