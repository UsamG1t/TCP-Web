---
title: REST API
parent: Guide
nav_order: 4
---

Base URL in production: `http://<host>/api` (proxied) or `http://<host>:5000`
(direct). In local development the frontend uses `http://localhost:5000`.

### `GET /health`

Liveness probe.

```bash
curl -s localhost:5000/health
# {"status": "ok"}
```

### `GET /schema`

Returns defaults, valid ranges, protocols, and retransmission modes. The frontend
builds its parameter form from this response.

```json
{
  "numeric": {
    "packetTime": { "default": 2500, "min": 100, "max": 10000 },
    "ackTime":    { "default": 1500, "min": 50,  "max": 5000  },
    "sendWindow": { "default": 4,    "min": 1,   "max": 64    },
    "recvWindow": { "default": 8,    "min": 1,   "max": 64    },
    "packetLoss": { "default": 5,    "min": 0,   "max": 50    },
    "ackLoss":    { "default": 2,    "min": 0,   "max": 50    },
    "timeout":    { "default": 8000, "min": 200, "max": 20000 },
    "bandwidth":  { "default": 10,   "min": 1,   "max": 100   }
  },
  "protocols": ["classic", "tahoe", "reno", "cubic"],
  "retransmitModes": ["gobackn", "selective"],
  "duration": { "default": 30, "min": 1, "max": 300 }
}
```

### `POST /simulate`

Runs a fresh simulation and returns the full event trace, a resumable checkpoint,
and summary statistics.

| Field          | Type    | Required | Meaning |
|----------------|---------|----------|---------|
| `config`       | object  | no       | Any subset of the schema parameters; missing values use defaults |
| `duration`     | number  | no       | Seconds of *additional* virtual time to simulate (default 30) |
| `seed`         | integer | no       | PRNG seed for reproducibility (default 1) |
| `resume_state` | object  | no       | A `checkpoint` from a previous call |

```bash
curl -s -X POST localhost:5000/simulate \
  -H 'Content-Type: application/json' \
  -d '{"config":{"protocol":"reno","packetLoss":8},"duration":10,"seed":42}'
```

Response: `{ "events": [...], "checkpoint": {...}, "stats": {...} }`. Validation
errors return `400`; an oversized trace returns `413`.

### Continuing a run (hybrid mode)

To extend a run, send the previous `checkpoint` back as `resume_state`. The new
`config` may differ — the continuation reflects the new parameters from that point
on, while packets already in flight keep their decided fate. This powers "Continue
with new parameters" in the UI.

```bash
curl -s -X POST localhost:5000/simulate -H 'Content-Type: application/json' \
  -d '{"config":{"protocol":"reno","packetLoss":8},"duration":10,"seed":42}' > run1.json

jq -c '{config:{protocol:"cubic",packetLoss:20},duration:10,resume_state:.checkpoint}' run1.json \
  | curl -s -X POST localhost:5000/simulate -H 'Content-Type: application/json' -d @-
```

### Event schema

Every event carries `t` (virtual milliseconds) and a `type`:

| Type               | Payload             | Meaning |
|--------------------|---------------------|---------|
| `packet_send`      | `seq`, `retransmit` | A data segment leaves the sender |
| `fast_retransmit`  | `seq`               | Segment retransmitted after 3 duplicate ACKs |
| `packet_deliver`   | `seq`               | Segment arrives at the receiver |
| `packet_drop`      | `seq`               | Segment lost in the network |
| `ack_send`         | `ack`               | Receiver emits a cumulative ACK |
| `ack_deliver`      | `ack`               | ACK arrives at the sender |
| `ack_drop`         | `ack`               | ACK lost |
| `dup_ack`          | `ack`, `count`      | Duplicate ACK observed by the sender |
| `timeout`          | `seq`               | Retransmission timer fired |
| `cwnd_change`      | `value`, `phase`, `reason` | Congestion window changed |
| `ssthresh_change`  | `value`             | Slow-start threshold changed |
| `phase_change`     | `phase`             | slow-start / congestion-avoidance / fast-recovery |
