---
title: Backend · API
parent: Code Reference
nav_order: 2
---

# Backend · API

*Generated from source by `docs/_tools/gen_code_docs.py`. Edit the docstrings in the code, then re-run the generator.*

### `backend/app.py`

Flask API for the TCP simulator.

Endpoints:
  GET  /health    -> liveness probe
  GET  /schema    -> defaults, ranges, protocols (drives the frontend form)
  POST /simulate  -> run (or continue) a simulation, return events + checkpoint

The backend is stateless: to "continue" a run, the client sends back the
checkpoint it received earlier, together with the (possibly new) config.

#### `health()`

_No description yet._

#### `get_schema()`

_No description yet._

#### `post_simulate()`

_No description yet._
