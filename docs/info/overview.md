---
title: Overview
parent: Guide
nav_order: 1
---

The project demonstrates how a TCP sender's window evolves as segments are sent,
acknowledged, delayed, and lost. Four congestion-control algorithms are
implemented — Classic, Tahoe, Reno, and CUBIC — over a common sliding-window model
with cumulative acknowledgements, duplicate-ACK detection, fast retransmit, and an
adaptive retransmission timer (RFC 6298).

The system has three deployable parts:

- a **backend** (Python / Flask) exposing a small REST API and containing the
  discrete-event simulation engine;
- a **frontend** (Svelte / Vite) that replays a computed trace;
- a **reverse proxy** (nginx) that serves both frontends and proxies the API.

When deployed, the trace player is served at `/latest/`, the interactive
click-to-drop simulator at `/old`, and the REST API is reachable both through the
reverse proxy at `/api/` and directly on port `5000`.
