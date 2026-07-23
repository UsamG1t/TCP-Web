---
title: Backend · API
parent: Code Reference
nav_order: 2
---

# Backend · API

*Generated from source by `docs/_tools/gen_code_docs.py`. Edit the docstrings in the code, then re-run the generator.*

### `backend/app.py`

HTTP API for the simulator.

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

#### `health()`

Report that the service is up. Returns `{"status": "ok"}`.

#### `get_schema()`

Return the parameter schema: defaults, ranges, protocols, modes.

The frontend builds its form from this response and validates locally
against the same bounds the server enforces.

#### `post_simulate()`

Run a simulation, or continue one, and return the resulting trace.

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
