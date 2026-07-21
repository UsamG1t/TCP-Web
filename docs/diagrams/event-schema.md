---
title: Event schema
parent: Diagrams
nav_order: 2
---

# Event trace — state model

The engine emits a flat list of timestamped events. The player derives everything
from them: paired *flights* for the ladder, and a per-event *state timeline* for
the readouts and charts.

```mermaid
stateDiagram-v2
  [*] --> slow_start
  slow_start --> congestion_avoidance: cwnd ≥ ssthresh
  congestion_avoidance --> fast_recovery: 3 duplicate ACKs (Reno/CUBIC)
  fast_recovery --> congestion_avoidance: new ACK
  slow_start --> slow_start: timeout (cwnd = 1)
  congestion_avoidance --> slow_start: timeout (cwnd = 1)
  fast_recovery --> slow_start: timeout (cwnd = 1)
```
