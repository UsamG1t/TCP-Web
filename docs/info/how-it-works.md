---
title: How It Works
parent: Guide
nav_order: 3
---

### Event-driven vs. real-time

Both frontends run the **same congestion-control rules**. They differ only in how
the clock advances.

The **backend engine** (`backend/engine`, reached through the API and used by
`/latest`) is a **discrete-event simulation**. It keeps a virtual clock and a
priority queue of future events (`send`, data arrival, ACK arrival, `RTO`). It
pops the earliest event, mutates state, schedules new events, and repeats until
the virtual clock reaches the requested duration. A 30-second run is computed in a
fraction of a second, because nothing waits on wall-clock time. Runs are seeded and
reproducible, and because the engine is a pure function of
`(config, seed, resume_state)` the backend keeps **no per-session state**.

The **interactive page** (`legacy/tcp_simulator.html`, served at `/old`) is a
JavaScript **port of that same engine** — same PRNG, same RTO estimator, same
congestion-control strategies, same sender and receiver. The only difference is
that its event queue is *paced*: events are released as a real clock advances,
scaled by the speed slider. That is what makes packets watchable in flight and
lets a user **drop a packet by clicking it** — a manual drop flips the `lost` flag
on an already scheduled arrival, so from TCP's point of view it is an ordinary
loss, and duplicate ACKs, fast retransmit, or an RTO follow on their own.

An earlier prototype advanced in real time on the server (using `time.sleep`),
which made a 30-second request block for 30 seconds. The discrete-event model
replaced it.

> **Cross-validated.** Given the same configuration and seed, and with no manual
> drops, the JavaScript engine produces an event trace **identical** to the Python
> engine's — event for event, including timestamps. `/old` and `/latest` are two
> views of one model, not two models.

### The three faces: `/old`, `/latest`, `/api`

| Path        | What it serves                              | Notes |
|-------------|---------------------------------------------|-------|
| `/latest/`  | Svelte trace player                         | Computes a trace via the API, then replays it: ladder diagram, sliding-window strip, cwnd chart, scrubbing |
| `/old`      | Interactive single-file simulator           | Runs the ported engine live in the browser; packets can be **dropped by clicking them** mid-flight. No build step, no API calls |
| `/api/*`    | REST API through the nginx reverse proxy    | Prefix `/api` is stripped before proxying |
| `:5000`     | REST API exposed directly on the port       | Same API, for curl / scripting |
