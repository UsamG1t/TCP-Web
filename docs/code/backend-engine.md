---
title: Backend · engine
parent: Code Reference
nav_order: 1
---

# Backend · engine

*Generated from source by `docs/_tools/gen_code_docs.py`. Edit the docstrings in the code, then re-run the generator.*

### `backend/engine/__init__.py`

TCP simulator engine (discrete-event, stateless).

---

### `backend/engine/config.py`

Simulation configuration: the Config dataclass plus a single source of truth
for defaults / valid ranges. Both the /schema endpoint (which drives the frontend
form) and validate_config() read from the same tables below.

#### `class Config`

_No description yet._

#### `Config.serialization_ms(self)`

_No description yet._

#### `schema()`

Metadata for the frontend to build its form and validate input.

#### `validate_config(raw: dict)`

Return a full, defaulted, validated config dict. Raise ValueError on bad input.

---

### `backend/engine/congestion.py`

Congestion-control strategies behind a common interface.

Each strategy mutates engine state (cwnd / ssthresh / phase); the engine itself
performs the actual (re)transmission. Protocols: classic, tahoe, reno, cubic.

References:
  RFC 5681 — slow start, congestion avoidance, fast retransmit / fast recovery
  RFC 6582 — NewReno fast recovery
  RFC 9438 — CUBIC (Standards Track; obsoletes RFC 8312)

#### `class CC`

_No description yet._

#### `CC.on_new_ack(self, e, acked: int, segments_acked: int = 1)`

_No description yet._

#### `CC.on_triple_dup_ack(self, e)`

_No description yet._

#### `CC.on_timeout(self, e)`

_No description yet._

#### `class Classic(CC)`

_No description yet._

#### `Classic.on_new_ack(self, e, acked, segments_acked = 1)`

_No description yet._

#### `Classic.on_triple_dup_ack(self, e)`

_No description yet._

#### `Classic.on_timeout(self, e)`

_No description yet._

#### `class SlowStartCA(CC)`

Shared slow-start + AIMD congestion avoidance (Tahoe/Reno).

#### `SlowStartCA._grow(self, e)`

_No description yet._

#### `SlowStartCA.on_new_ack(self, e, acked, segments_acked = 1)`

_No description yet._

#### `class Tahoe(SlowStartCA)`

_No description yet._

#### `Tahoe.on_triple_dup_ack(self, e)`

_No description yet._

#### `class Reno(SlowStartCA)`

_No description yet._

#### `Reno.on_triple_dup_ack(self, e)`

_No description yet._

#### `class Cubic(CC)`

CUBIC per RFC 9438.

Implements: the cubic window function (Sec. 4.2), the concave/convex regions
(4.4, 4.5), the Reno-friendly region via W_est (4.3), multiplicative decrease
based on flight_size (4.6), and the timeout rules (4.8).

Fast convergence (4.7) is deliberately NOT implemented: it only matters when
several CUBIC flows share a bottleneck, and 4.7 states it SHOULD be disabled
for a single flow — exactly the case this simulator models. HyStart++ (4.10)
is likewise omitted; plain Reno-style slow start is the allowed fallback.

#### `Cubic._start_epoch(e)`

Begin a congestion-avoidance stage: fix t_epoch, cwnd_epoch, W_max, K, W_est.

#### `Cubic._w_cubic(cu, t_s)`

W_cubic(t) = C*(t - K)^3 + W_max   (4.2, Figure 1).

#### `Cubic.on_new_ack(self, e, acked, segments_acked = 1)`

_No description yet._

#### `Cubic.on_triple_dup_ack(self, e)`

_No description yet._

#### `Cubic.on_timeout(self, e)`

_No description yet._

---

### `backend/engine/core.py`

Discrete-event simulation core.

Virtual-time event queue drives sender / receiver / loss / detection. A run
computes instantly and returns an event trace plus a fully serializable
checkpoint (including the pending event queue and PRNG state) so a run can be
continued later — possibly with new parameters (the "hybrid" model).

#### `class Engine`

_No description yet._

#### `Engine.__init__(self, cfg: Config, seed: int = 1)`

_No description yet._

#### `Engine.eff_window(self)`

_No description yet._

#### `Engine.flight_size(self)`

Segments sent but not yet acknowledged (RFC 9438 §4.6 uses this).

#### `Engine.srtt_s(self)`

Smoothed RTT in seconds; falls back to the nominal path RTT.

#### `Engine.emit(self, etype: str, **payload)`

_No description yet._

#### `Engine.set_cwnd(self, value, reason = '')`

_No description yet._

#### `Engine.set_phase(self, phase)`

_No description yet._

#### `Engine.emit_ssthresh(self)`

_No description yet._

#### `Engine._push(self, t, kind, data)`

_No description yet._

#### `Engine._start_timer(self)`

_No description yet._

#### `Engine._stop_timer(self)`

_No description yet._

#### `Engine._schedule_send(self, t)`

_No description yet._

#### `Engine._transmit(self, seq, retransmit, fast = False)`

_No description yet._

#### `Engine.fast_retransmit(self)`

Retransmit the oldest unacked segment (triple-dup-ack).

#### `Engine._handle_send(self)`

_No description yet._

#### `Engine._handle_data_arrive(self, seq)`

_No description yet._

#### `Engine._handle_data_drop(self, seq)`

_No description yet._

#### `Engine._handle_ack(self, ack)`

_No description yet._

#### `Engine._handle_rto(self, gen)`

_No description yet._

#### `Engine.run(self, until_ms: int)`

_No description yet._

#### `Engine.checkpoint(self)`

_No description yet._

#### `Engine.resume(cls, checkpoint: dict, new_cfg: Config | None = None)`

_No description yet._

#### `simulate(config: dict, duration_s: int, seed: int = 1, resume_state: dict | None = None)`

Public entry point used by the Flask layer.

config       : validated config dict
duration_s   : how many *additional* seconds to simulate
resume_state : a checkpoint from a previous call (or None for a fresh run)

---

### `backend/engine/prng.py`

Deterministic PRNG (splitmix64). State is a single 64-bit int → JSON-clean,
so it can be serialized into a checkpoint and restored exactly (reproducible runs
and reproducible "continue").

#### `class PRNG`

_No description yet._

#### `PRNG.__init__(self, state: int)`

_No description yet._

#### `PRNG.next_u64(self)`

_No description yet._

#### `PRNG.chance(self, percent: float)`

True with probability percent/100.

---

### `backend/engine/rto.py`

Adaptive retransmission timeout per RFC 6298.

SRTT / RTTVAR smoothed estimators, RTO = SRTT + max(G, K*RTTVAR) with K=4,
alpha=1/8, beta=1/4. Karn's algorithm (skip RTT samples from retransmitted
segments) is enforced by the caller. Exponential backoff on timeout.

#### `class RtoEstimator`

_No description yet._

#### `RtoEstimator.update(self, r: float)`

Incorporate one RTT sample R (ms). (Karn handled by caller.)

#### `RtoEstimator.backoff(self)`

_No description yet._

#### `RtoEstimator._clamp(self, v: float)`

_No description yet._
