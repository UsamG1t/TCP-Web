---
title: Home
nav_order: 1
---

# TCP Sliding-Window Simulator

An educational simulator of TCP sliding-window flow control and congestion-control
algorithms — **Classic**, **Tahoe**, **Reno**, and **CUBIC** — over a common
sliding-window model with cumulative ACKs, fast retransmit, and an adaptive
retransmission timer.

The backend computes a whole transmission run as a discrete-event trace (instantly,
in virtual time). The `/latest` frontend replays that trace as an animated
time-sequence diagram, a sliding-window strip, and a congestion-window chart. The
`/old` page runs the very same rules live in the browser and lets you drop packets
by clicking them.

## How this documentation is organised

- **Guide** — the narrative documentation (overview, architecture, API, protocols,
  deployment). These chapters are the single source of truth and are also assembled
  into the repository `README.md`.
- **Code Reference** — per-module API extracted automatically from the source
  (Python docstrings, JavaScript JSDoc).
- **Diagrams** — architecture and data-flow diagrams (Mermaid).

> The chapters under **Guide** double as the source for `README.md`: edit the
> chapter, then run `python3 docs/_tools/build_readme.py`. The **Code Reference**
> pages are produced by `python3 docs/_tools/gen_code_docs.py`.
