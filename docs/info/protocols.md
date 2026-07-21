---
title: Sliding Window Protocols
parent: Guide
nav_order: 5
---

There is only one set of rules: the Python engine (`backend/engine`) and its
JavaScript port (`legacy/tcp_simulator.html`) implement the same behaviour and are
verified to produce identical traces, so everything below applies equally to
`/latest` and `/old`. Congestion control affects the **sender**; the **receiver**
behaves the same across all four protocols and depends only on the retransmission
mode.

### Common model

**What we emulate.** A one-way data channel with propagation delay `packetTime`,
a return channel with delay `ackTime`, a bottleneck that serializes segments at
`bandwidth` segments/second, and independent stochastic loss of data
(`packetLoss` %) and ACKs (`ackLoss` %). Sequence numbers count segments.

**Sender (common behaviour).**

1. Keeps `cwnd`, `ssthresh`, `sendBase` (oldest unacknowledged segment), and
   `nextSeq`.
2. May send while `nextSeq - sendBase < min(cwnd, recvWindow)` — the effective
   window is the smaller of congestion window and the receiver's advertised
   window. New segments are spaced by the link serialization time.
3. On a new cumulative ACK: advances `sendBase`, takes an RTT sample (unless the
   acknowledged segment was retransmitted — Karn's rule), updates `cwnd` per the
   protocol, and restarts the RTO timer.
4. On the third duplicate ACK: fast-retransmits `sendBase` and applies the
   protocol's loss reaction.
5. On RTO expiry: applies the protocol's timeout reaction, backs off the timer,
   and retransmits. In **go-back-n** it rewinds `nextSeq` to `sendBase` and resends
   the window; in **selective repeat** it resends only `sendBase`.

**Receiver (common behaviour).** Tracks `expected`. In-order segments advance
`expected` and are cumulatively acknowledged; out-of-order segments are discarded
(go-back-n) or buffered within `recvWindow` (selective repeat), and a duplicate ACK
is sent. ACKs may be lost according to `ackLoss`.

### Retransmission timeout (RFC 6298)

The RTO is adaptive. The sender keeps a smoothed RTT (`SRTT`) and its variation
(`RTTVAR`):

```
first sample R:   SRTT = R;  RTTVAR = R/2
later samples R':  RTTVAR = (1 - 1/4)*RTTVAR + 1/4*|SRTT - R'|
                   SRTT   = (1 - 1/8)*SRTT   + 1/8*R'
RTO = SRTT + max(G, 4 * RTTVAR)          # clamped to [RTO_min, RTO_max]
```

**Karn's algorithm** — RTT is never sampled from a retransmitted segment.
**Exponential backoff** — the RTO doubles when the timer fires. The `timeout`
parameter seeds the initial RTO; it then converges toward the channel's real RTT.

### Classic

A fixed-window baseline with no congestion control.

- **Sender:** `cwnd` is pinned to `sendWindow` and never changes. Loss still
  triggers retransmission (reliability is preserved), but the window never reacts.
- **Receiver:** standard cumulative-ACK behaviour.

### Tahoe

Slow start, AIMD congestion avoidance, and fast retransmit — but no fast recovery.
Any loss collapses the window to 1 (Jacobson 1988; RFC 5681).

- **Sender:** slow start (`cwnd += 1` per ACK) until `ssthresh`, then congestion
  avoidance (`cwnd += 1/cwnd` per ACK). On 3 duplicate ACKs *or* a timeout:
  `ssthresh = max(cwnd/2, 2)`, `cwnd = 1`, re-enter slow start (fast-retransmit on
  the duplicate-ACK path).

### Reno

Tahoe plus fast recovery: three duplicate ACKs halve the window instead of
resetting it (RFC 5681; NewReno, RFC 6582).

- **Sender:** slow start and congestion avoidance as in Tahoe. On 3 duplicate ACKs:
  `ssthresh = max(cwnd/2, 2)`, `cwnd = ssthresh + 3`, enter fast recovery,
  fast-retransmit; each further duplicate ACK inflates `cwnd` by 1; the next new ACK
  deflates to `cwnd = ssthresh` and returns to congestion avoidance. On timeout:
  `cwnd = 1`, slow start.

### CUBIC

A window-growth function that is cubic in the time since the last congestion
event, for high-bandwidth, long-delay paths. Standardised in **RFC 9438** (which
obsoletes RFC 8312). Constants: `C = 0.4`, `β_cubic = 0.7`,
`α_cubic = 3(1 − β)/(1 + β) ≈ 0.53`.

- **Sender:**
  - *Slow start*: as in Reno (`cwnd += segments_acked`). HyStart++ (§4.10) is not
    used; plain slow start is the permitted fallback.
  - *Congestion avoidance* (§4.2, §4.4, §4.5): at the start of each CA stage the
    sender fixes `t_epoch`, `cwnd_epoch`, `W_max`, and
    `K = ∛((W_max − cwnd_epoch)/C)`. On every ACK it evaluates the cubic function
    one RTT ahead, `W_cubic(t + RTT) = C·(t + RTT − K)³ + W_max`, clamps the result
    to `[cwnd, 1.5·cwnd]`, and advances `cwnd += (target − cwnd)/cwnd`. Growth is
    *concave* while `cwnd < W_max` and *convex* afterwards.
  - *Reno-friendly region* (§4.3): in parallel it maintains
    `W_est += α_cubic · segments_acked / cwnd` from `cwnd_epoch`, with `α_cubic → 1`
    once `W_est ≥ cwnd_prior`. When the cubic curve would grow more slowly than
    Reno, `cwnd` is set to `W_est` instead.
  - *On 3 duplicate ACKs* (§4.6): `ssthresh = max(flight_size · β_cubic, 2)` (the
    reduction is based on **flight_size**, and the factor is 0.7 — not one half),
    `cwnd = cwnd · β_cubic`, enter fast recovery, fast-retransmit; the next CA stage
    probes back toward `W_max = cwnd_prior`.
  - *On timeout* (§4.8): `cwnd` collapses to 1 and slow start resumes, but
    `ssthresh` is set with `β_cubic` rather than one half; the first CA stage
    afterwards uses `K = 0`.
- **Receiver:** common cumulative-ACK behaviour.

> **Scope note.** *Fast convergence* (§4.7) is intentionally not implemented: it
> only affects how several CUBIC flows share a bottleneck, and RFC 9438 states it
> SHOULD be disabled for a single flow — which is what this simulator models.
> RTT-fairness and Reno-vs-CUBIC competition (§3.3, §5.1) are likewise out of scope
> for a single-flow model, and the optional mechanisms PRR (RFC 6937) and
> spurious-loss reversal (§4.9) are not used.
