# TCP Sliding Window Simulator

An interactive web-based simulator for demonstrating TCP protocol behavior with sliding window mechanisms. The simulator visualizes packet transmission between sender and receiver, supports multiple TCP congestion control algorithms, and provides both an interactive GUI and a REST API for programmatic access.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Deployment](#deployment)
- [REST API](#rest-api)
- [Protocols Workflow](#protocols-workflow)
  - [Classic Sliding Window](#classic-sliding-window)
  - [TCP Reno](#tcp-reno)
- [Interactive Controls](#interactive-controls)
- [Statistics](#statistics)
- [Configuration Parameters](#configuration-parameters)

---

## Overview

The TCP Sliding Window Simulator provides a real-time visualization of how TCP manages reliable data transfer between two endpoints. Two horizontal lanes represent the sender (top) and receiver (bottom). Data packets travel downward from sender to receiver, while ACK packets travel upward from receiver to sender. Each packet occupies its own horizontal slot based on its sequence number, preventing overlap and ensuring clear visibility.

The timeline is horizontally scrollable — users can navigate forward and backward to observe the entire transmission history. The viewport automatically follows active transmissions, shifting left as packets progress beyond two-thirds of the visible area.

---

## Architecture

```
┌─────────────────────────────────────────┐
│  Browser (Frontend)                   │
│  - Interactive visualization            │
│  - Real-time packet animation           │
│  - Parameter controls                   │
└─────────────┬───────────────────────────┘
              │ HTTP / REST
┌─────────────▼───────────────────────────┐
│  NGINX (Reverse Proxy)                  │
│  - Static file serving                  │
│  - API routing to backend               │
└─────────────┬───────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│  Python Flask (Backend)                 │
│  - REST API endpoints                   │
│  - Headless simulation engine           │
└─────────────────────────────────────────┘
```

| Component | Technology | File |
|-----------|-----------|------|
| Frontend | HTML5 / CSS3 / Vanilla JS | `tcp_simulator.html` |
| Backend | Python 3.11 + Flask + Flask-CORS | `app.py` |
| Proxy | NGINX | `nginx.conf` |
| Orchestration | Docker Compose | `docker-compose.yml` |

---

## Features

### Interactive Visualization
- **Two separate lanes**: sender (top, blue window) and receiver (bottom, green window)
- **Vertical packet movement**: data packets fly downward, ACK packets fly upward
- **Horizontal slot allocation**: each packet has its own slot based on sequence number — no overlap
- **Scrollable timeline**: mouse wheel or drag to navigate the entire transmission history
- **Auto-follow**: viewport automatically scrolls to keep active transmissions visible
- **Click-to-drop**: click any flying packet to manually drop it and observe protocol recovery

### Supported Protocols
- **Classic Sliding Window** — fixed-size window, no congestion control
- **TCP Tahoe** — Slow Start + Congestion Avoidance, timeout-based recovery
- **TCP Reno** — Tahoe + Fast Retransmit + Fast Recovery (3 dup ACKs)
- **TCP CUBIC** — cubic growth function for high-bandwidth networks
- **TCP BBR** — Bottleneck Bandwidth and RTT-based model

### Retransmission Modes
- **Go-Back-N** (default): on timeout, retransmit ALL unacknowledged packets starting from the lost one
- **Selective**: on timeout, retransmit ONLY the lost packet (configurable via UI)

### Real-time Controls
- Start / Pause / Reset simulation
- Speed multiplier (0.1x – 3.0x)
- All TCP parameters editable in real-time
- Event log panel with color-coded messages

---

## Deployment

### Option 1: Docker Compose (Recommended)

```bash
# Clone or download the project files
cd tcp-sliding-window-simulator

# Start all services
docker-compose up -d

# Access the simulator
open http://localhost
# or http://tcpsw.usamg1t.com (with DNS configured)
```

### Option 2: Manual Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Start the backend
python app.py

# 3. Configure NGINX using the provided nginx.conf
# 4. Place tcp_simulator.html in /var/www/tcp-simulator/
# 5. Restart NGINX
```

---

## REST API

### `GET /parameters`

Returns the current simulation configuration.

**Response:**
```json
{
  "success": true,
  "data": {
    "packetTime": 1000,
    "ackTime": 500,
    "sendWindow": 4,
    "recvWindow": 8,
    "protocol": "reno",
    "packetLoss": 5,
    "ackLoss": 2,
    "timeout": 3000,
    "bandwidth": 10,
    "retransmitMode": "gobackn"
  }
}
```

---

### `POST /set`

Updates simulation parameters. Invalid values return an error with valid options.

**Request body:**
```json
{
  "packetTime": 1000,
  "ackTime": 500,
  "sendWindow": 4,
  "recvWindow": 8,
  "protocol": "reno",
  "packetLoss": 5,
  "ackLoss": 2,
  "timeout": 3000,
  "bandwidth": 10,
  "retransmitMode": "gobackn"
}
```

**Valid `protocol` values:** `classic`, `tahoe`, `reno`, `cubic`, `bbr`
**Valid `retransmitMode` values:** `gobackn`, `selective`

**Error response (invalid protocol):**
```json
{
  "success": false,
  "error": "Invalid protocol",
  "validValues": ["classic", "tahoe", "reno", "cubic", "bbr"]
}
```

---

### `POST /play`

Runs a headless simulation for the specified duration and returns statistics.

**Request body:**
```json
{
  "duration": 30
}
```

**Response:**
```json
{
  "success": true,
  "duration": 30,
  "statistics": {
    "packetsSent": 150,
    "packetsReceived": 142,
    "acksSent": 142,
    "acksReceived": 138,
    "packetLossPercent": 5.33,
    "ackLossPercent": 2.82,
    "windowHistory": [
      {"timestamp": 1719830400000, "value": 4.0},
      {"timestamp": 1719830405000, "value": 5.0}
    ],
    "ssthreshHistory": [
      {"timestamp": 1719830400000, "value": 64.0},
      {"timestamp": 1719830420000, "value": 32.0}
    ]
  }
}
```

---

## Protocols Workflow

This section describes the detailed behavior of each supported protocol as implemented in the simulator.

---

### Classic Sliding Window

The simplest form of sliding window protocol with **no congestion control**. It demonstrates the basic mechanics of window-based flow control without any adaptation to network conditions.

#### State Variables
| Variable | Description |
|----------|-------------|
| `sendBase` | First unacknowledged sequence number |
| `nextSeqNum` | Next sequence number to send |
| `expectedSeqNum` | Next expected sequence number at receiver |
| `cwnd` | Congestion window size (fixed, never changes) |

#### Sender Behavior
1. The sender maintains a fixed-size window (`cwnd` = initial `sendWindow`).
2. Packets are sent sequentially while `nextSeqNum < sendBase + cwnd`.
3. Each packet has an **individual timeout timer**.
4. When a packet is sent, a timer is started. If the timer expires before the corresponding ACK is received, a **timeout** occurs.

#### Timeout Handling
- On timeout: **no congestion control actions** are performed.
- The window size (`cwnd`) remains unchanged.
- **Go-Back-N retransmission**: all unacknowledged packets starting from `sendBase` are retransmitted.
- `nextSeqNum` is reset to `sendBase`.

#### ACK Handling
- ACKs are **cumulative**: `ACK=N` confirms receipt of all packets `0` through `N`.
- On receiving `ACK=N`: `sendBase` is set to `N + 1`, and the window slides forward.
- Duplicate ACKs (ACK < `sendBase`) are ignored.

#### Receiver Behavior
- The receiver expects packets in strict sequential order.
- On receiving packet `N` where `N == expectedSeqNum`:
  - `expectedSeqNum` is incremented.
  - Any buffered out-of-order packets are processed.
  - A cumulative `ACK = expectedSeqNum - 1` is sent.
- On receiving packet `N` where `N > expectedSeqNum`:
  - The packet is buffered.
  - A **duplicate ACK** for `expectedSeqNum - 1` is sent.
- On receiving packet `N` where `N < expectedSeqNum`:
  - The packet is a duplicate; a cumulative ACK is sent anyway.

#### Key Characteristics
- **No Slow Start, no Congestion Avoidance**.
- Window size never changes regardless of losses.
- Simplest model for understanding basic sliding window mechanics.

---

### TCP Reno

TCP Reno is the most widely deployed TCP congestion control algorithm. It combines **Slow Start**, **Congestion Avoidance**, **Fast Retransmit**, and **Fast Recovery** to adaptively control the transmission rate.

#### State Variables
| Variable | Description |
|----------|-------------|
| `cwnd` | Congestion window size (dynamic) |
| `ssthresh` | Slow start threshold |
| `sendBase` | First unacknowledged sequence number |
| `nextSeqNum` | Next sequence number to send |
| `expectedSeqNum` | Next expected sequence number at receiver |
| `phase` | Current phase: `slow-start`, `congestion-avoidance`, or `fast-recovery` |
| `dupAckCount` | Count of consecutive duplicate ACKs |
| `acksInCurrentWindow` | Count of ACKs received in the current congestion window |

#### Phase 1: Slow Start

**Entry condition:** Initial connection or after a timeout.

**Behavior:**
- `cwnd` starts at the configured `sendWindow` (typically 1–4 MSS).
- `ssthresh` starts at `max(sendWindow × 4, 64)`.
- For **every new ACK received**, `cwnd` is increased by **1**.
- This results in **exponential growth**: window doubles every RTT.

```
On new ACK during Slow Start:
    cwnd ← cwnd + 1
    if cwnd ≥ ssthresh:
        phase ← "congestion-avoidance"
        acksInCurrentWindow ← 0
```

**Example:**
```
RTT 0: cwnd = 4, send packets 0,1,2,3
        → receive ACKs for 0,1,2,3
RTT 1: cwnd = 8, send packets 4,5,6,7,8,9,10,11
        → receive ACKs for 4..11
RTT 2: cwnd = 16, ...
```

---

#### Phase 2: Congestion Avoidance

**Entry condition:** `cwnd` reaches `ssthresh` during Slow Start, or exiting Fast Recovery.

**Behavior:**
- Growth is **linear** rather than exponential.
- The sender counts ACKs received (`acksInCurrentWindow`).
- After receiving ACKs for **all packets in the current window** (i.e., `acksInCurrentWindow >= floor(cwnd)`), `cwnd` is increased by **1**.
- This means the window grows by approximately **1 MSS per RTT**.

```
On new ACK during Congestion Avoidance:
    acksInCurrentWindow ← acksInCurrentWindow + 1
    if acksInCurrentWindow ≥ floor(cwnd):
        cwnd ← cwnd + 1
        acksInCurrentWindow ← 0
```

**Example:**
```
cwnd = 5.0
Send packets 20,21,22,23,24
Receive ACKs for 20,21,22,23,24 → acksInCurrentWindow = 5
5 ≥ 5 → cwnd = 6.0, acksInCurrentWindow = 0

Next round: send packets 25,26,27,28,29,30 (6 packets)
Receive 6 ACKs → acksInCurrentWindow = 6
6 ≥ 6 → cwnd = 7.0
```

---

#### Timeout Handling

A timeout is the most severe signal of network congestion. It occurs when an individual packet timer expires before its ACK is received.

**Important:** The sender does **NOT** react to packet loss detected in the channel (e.g., a packet being dropped by the network or manually by the user). The sender only reacts when:
1. A **timeout** fires, or
2. **Three duplicate ACKs** are received.

**On timeout:**
```
ssthresh ← max(floor(cwnd / 2), 2)
cwnd ← 1
phase ← "slow-start"
acksInCurrentWindow ← 0
dupAckCount ← 0
```

**Go-Back-N retransmission:**
- All unacknowledged packets from `sendBase` to `nextSeqNum - 1` are retransmitted.
- `nextSeqNum` is reset to `sendBase`.
- All old in-flight packets are marked as lost and their timers cleared.

**Example:**
```
Before timeout: cwnd = 16, ssthresh = 64, sendBase = 20, nextSeqNum = 36
Packet #22 times out
After timeout:  cwnd = 1,  ssthresh = 8
                Go-Back-N: retransmit packets 20,21,22,...,35
                nextSeqNum = 20
```

---

#### Fast Retransmit (3 Duplicate ACKs)

Fast Retransmit allows the sender to detect packet loss **without waiting for a timeout**, based on duplicate ACKs from the receiver.

**Mechanism:**
- The receiver sends a **duplicate ACK** for `expectedSeqNum - 1` whenever it receives an out-of-order packet.
- The sender counts duplicate ACKs for the same sequence number.
- On the **third duplicate ACK** (`dupAckCount == 3`):

```
// Fast Retransmit + Fast Recovery entry
ssthresh ← max(floor(cwnd / 2), 2)
cwnd ← ssthresh + 3
phase ← "fast-recovery"
```

**Why `cwnd = ssthresh + 3`?**
- The `+3` accounts for the three packets that have already left the network (the ones that triggered the duplicate ACKs).
- This "inflates" the window so the sender can continue transmitting new packets while waiting for the retransmission to succeed.

**Fast Retransmit:**
- The lost packet (sequence number = `lastDupAck + 1`) is retransmitted **immediately**.
- Only this single packet is retransmitted (not Go-Back-N).

---

#### Phase 3: Fast Recovery

**Entry condition:** Third duplicate ACK received.

**Behavior:**
- The sender remains in Fast Recovery until a **new ACK** (non-duplicate) is received.
- For **each additional duplicate ACK** received beyond the third:
  ```
  cwnd ← cwnd + 1
  ```
  This inflation allows the sender to keep the pipe full by sending new packets as ACKs arrive.

**Exit condition: New ACK received**
```
// Deflate the window
cwnd ← ssthresh
phase ← "congestion-avoidance"
acksInCurrentWindow ← 0
```

**Example of full Fast Recovery cycle:**
```
1. Sender transmits packets 10,11,12,13,14,15,16 (cwnd = 7)
2. Packet #12 is lost
3. Packets 13,14,15,16 arrive at receiver out of order
4. Receiver sends: ACK=11, ACK=11, ACK=11, ACK=11 (4 dup ACKs for 11)

5. On 3rd dup ACK (ACK=11):
   ssthresh = floor(7/2) = 3
   cwnd = 3 + 3 = 6
   phase = "fast-recovery"
   Fast Retransmit packet #12

6. On 4th dup ACK (ACK=11):
   cwnd = 6 + 1 = 7
   (sender can now send one new packet, e.g., #17)

7. Retransmitted packet #12 arrives at receiver
8. Receiver now has 12,13,14,15,16 → sends cumulative ACK=16

9. On new ACK=16:
   cwnd = ssthresh = 3
   phase = "congestion-avoidance"
```

---

#### Complete State Machine Diagram

```
                    ┌─────────────────┐
                    │   Slow Start    │
                    │   cwnd = 1      │
                    │   (after TO)    │
                    └────────┬────────┘
                             │ new ACK: cwnd += 1
                             │
              cwnd < ssthresh│              cwnd >= ssthresh
         ┌───────────────────┘              └───────────────────┐
         │                                                    │
         ▼                                                    ▼
┌─────────────────┐                              ┌─────────────────────────┐
│   Slow Start    │                              │  Congestion Avoidance   │
│  (exponential)  │                              │    (linear growth)      │
│  cwnd += 1/ACK  │                              │  cwnd += 1 per window   │
└─────────────────┘                              └───────────┬─────────────┘
                                                             │
                                    ┌────────────────────────┼────────────────────────┐
                                    │                        │                        │
                                    │ timeout                │ 3× dup ACK             │
                                    ▼                        ▼                        │
                           ┌─────────────┐          ┌─────────────────┐               │
                           │   Timeout   │          │ Fast Retransmit │               │
                           │  ssthresh/=2│          │ ssthresh = cwnd/2│              │
                           │  cwnd = 1   │          │ cwnd = ssthresh+3│               │
                           │  GBN retrans│          │  retransmit 1 pkt│               │
                           └──────┬──────┘          └────────┬────────┘               │
                                  │                          │                        │
                                  │                          ▼                        │
                                  │                 ┌─────────────────┐               │
                                  │                 │  Fast Recovery  │               │
                                  │                 │  cwnd += 1/dup  │               │
                                  │                 └────────┬────────┘               │
                                  │                          │                        │
                                  │                          │ new ACK                │
                                  │                          ▼                        │
                                  │                 ┌─────────────────┐               │
                                  │                 │      Exit       │               │
                                  │                 │  cwnd = ssthresh│               │
                                  │                 │  phase = CA     │───────────────┘
                                  │                 └─────────────────┘
                                  │
                                  └────────────────────────────────────────────────────►
                                                          (back to Slow Start)
```

---

## Interactive Controls

| Control | Description |
|---------|-------------|
| **Packet transmission time** | Duration (ms) for a data packet to travel from sender to receiver |
| **ACK transmission time** | Duration (ms) for an ACK to travel from receiver to sender |
| **Initial send window** | Starting `cwnd` value |
| **Initial receive window** | Starting receiver window size |
| **Protocol** | `classic`, `tahoe`, `reno`, `cubic`, `bbr` |
| **Packet loss %** | Probability of random packet loss in the forward channel |
| **ACK loss %** | Probability of random ACK loss in the reverse channel |
| **Timeout** | Timer duration (ms) for individual packet retransmission |
| **Bandwidth** | Maximum packets per second the sender attempts to inject |
| **Retransmit mode** | `gobackn` (all from lost) or `selective` (only lost) |
| **Speed** | Simulation speed multiplier (0.1x – 3.0x) |

---

## Statistics

The top bar displays real-time statistics:

| Statistic | Description |
|-----------|-------------|
| Packets sent | Total data packets transmitted by sender |
| Packets received | Total data packets successfully received |
| ACKs sent | Total ACK packets transmitted by receiver |
| ACKs received | Total ACK packets successfully received by sender |
| Packets lost | Total data packets lost (channel + manual) |
| Current window | Current `cwnd` value |
| ssthresh | Current slow start threshold |
| Phase | Current congestion control phase |

---

## Configuration Parameters

All parameters can be set via the UI or the REST API `/set` endpoint.

| Parameter | Type | Range | Default | Description |
|-----------|------|-------|---------|-------------|
| `packetTime` | integer | 100–10000 | 1000 | Data packet one-way latency (ms) |
| `ackTime` | integer | 50–5000 | 500 | ACK packet one-way latency (ms) |
| `sendWindow` | integer | 1–64 | 4 | Initial congestion window |
| `recvWindow` | integer | 1–64 | 8 | Receiver window size |
| `protocol` | string | enum | `reno` | Congestion control algorithm |
| `packetLoss` | integer | 0–50 | 5 | Forward channel loss probability (%) |
| `ackLoss` | integer | 0–50 | 2 | Reverse channel loss probability (%) |
| `timeout` | integer | 500–20000 | 3000 | Per-packet retransmission timeout (ms) |
| `bandwidth` | integer | 1–100 | 10 | Maximum send attempts per second |
| `retransmitMode` | string | `gobackn`/`selective` | `gobackn` | Retransmission strategy |

