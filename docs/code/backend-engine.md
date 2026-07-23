---
title: Backend · engine
parent: Code Reference
nav_order: 1
---

# Backend · engine

*Generated from source by `docs/_tools/gen_code_docs.py`. Edit the docstrings in the code, then re-run the generator.*

### `backend/engine/__init__.py`

Discrete-event TCP simulation engine.

A self-contained package with no web framework in it, so it can be exercised
directly from a REPL or a test without starting a server. The API layer imports
`simulate()`; everything else is available for scripting and experimentation.

Modules:

- `core` — the event loop, sender, receiver and checkpointing.
- `congestion` — the four congestion-control strategies.
- `rto` — the adaptive retransmission timer (RFC 6298).
- `prng` — the deterministic generator behind reproducible loss.
- `config` — parameters, defaults, ranges and validation.

---

### `backend/engine/config.py`

Simulation parameters: definitions, defaults, ranges and validation.

This module is the single source of truth for what a simulation can be asked to
do. The tables below feed three consumers at once, which is why they live in one
place: the `/schema` endpoint publishes them so the frontend can build its form,
`validate_config()` enforces them on every request, and `Config` carries the
resulting values into the engine.

Adding a numeric parameter is therefore a one-line change to `NUMERIC_PARAMS`
plus a matching field on `Config`; the API schema and the input validation
follow automatically.

#### `class Config`

One simulation's parameters, in the form the engine consumes.

Field meanings are documented on `NUMERIC_PARAMS`; the defaults here mirror
that table. Two additional fields select behaviour rather than magnitude:

- `protocol` — one of `VALID_PROTOCOLS`; picks the congestion-control
  strategy.
- `retransmitMode` — one of `VALID_RETRANSMIT`. Under `gobackn` a timeout
  rewinds the sender and the receiver discards anything out of order; under
  `selective` only the missing segment is resent and the receiver buffers
  what arrives early.

Instances are created from an already validated dictionary, so the class
itself performs no checking.

#### `Config.serialization_ms(self)`

Milliseconds the bottleneck needs to put one segment on the wire.

This is the spacing between successive transmissions — the simulated
equivalent of a link's serialization delay — derived from `bandwidth`.

#### `schema()`

Describe every parameter so a client can build and pre-validate a form.

Returned by `GET /schema`. The payload contains the numeric parameters with
their default, minimum and maximum, the list of protocols, the list of
retransmission modes, and the accepted range for `duration`.

Publishing the schema rather than hard-coding it in the frontend keeps the
two in step: changing a bound here immediately changes what the UI offers.

#### `validate_config(raw: dict)`

Check a client-supplied configuration and fill in what it omitted.

Every field is optional: anything absent from `raw` takes its default, so a
request may specify only what it cares about. Values that are present are
checked for type and range. Booleans are rejected for numeric fields on
purpose — Python treats `True` as `1`, and silently accepting it would hide
a client bug.

- `raw` — the untrusted `config` object from a request body.

Returns a complete configuration dictionary suitable for `Config(**cfg)`.

Raises `ValueError` with a human-readable message if any value is of the
wrong type, out of range, or not a recognised protocol or retransmission
mode. The API layer turns that message into an HTTP 400 response.

---

### `backend/engine/congestion.py`

Congestion-control algorithms.

Each algorithm is a small strategy object with three hooks — a new
acknowledgement arrived, three duplicate acknowledgements arrived, the
retransmission timer fired — and the engine calls whichever one applies. The
strategies only decide *how the window should react*; scheduling, transmission
and the receiver's behaviour stay in `engine.core`, identical for all four
protocols.

The four implementations form a deliberate progression, which is what makes them
worth comparing side by side:

- **Classic** — a fixed window, no congestion control at all. The baseline.
- **Tahoe** — slow start and additive-increase congestion avoidance; every loss
  collapses the window to one segment.
- **Reno** — adds fast recovery, so a loss detected by duplicate ACKs only halves
  the window instead of resetting it.
- **CUBIC** — replaces the linear increase with a cubic function of the time
  since the last loss, for paths with a large bandwidth-delay product.

Standards implemented here: RFC 5681 (slow start, congestion avoidance, fast
retransmit and fast recovery), RFC 6582 (NewReno-style fast recovery) and
RFC 9438 (CUBIC, Standards Track, obsoletes RFC 8312).

#### `class CC`

Interface shared by every congestion-control strategy.

Subclasses receive the live `Engine` as their first argument and mutate its
`cwnd`, `ssthresh` and `phase` directly, emitting trace events through the
engine's helpers. They never transmit or schedule anything themselves; the
engine does that once the strategy has decided.

The default `on_timeout()` implements the classic RFC 5681 reaction and is
inherited by Tahoe and Reno unchanged.

#### `CC.on_new_ack(self, e, acked: int, segments_acked: int = 1)`

React to an acknowledgement that advanced the sender's window.

Called only outside fast recovery; while in fast recovery the engine
handles window deflation itself.

- `e` — the engine, whose sender state is to be updated.
- `acked` — the cumulative acknowledgement number just received.
- `segments_acked` — how many segments this acknowledgement covers.
  Cumulative ACKs can confirm several at once, and CUBIC scales its
  increase by this count (RFC 9438 §4.3).

#### `CC.on_triple_dup_ack(self, e)`

React to the third duplicate acknowledgement for the same segment.

Three duplicates are TCP's signal that one segment went missing while
later ones arrived — a loss worth reacting to immediately rather than
waiting for the timer. Implementations are expected to call
`e.fast_retransmit()` so the missing segment is resent.

#### `CC.on_timeout(self, e)`

React to expiry of the retransmission timer (RFC 5681 §3.1).

A timeout is the harshest loss signal available: nothing has been
acknowledged for a whole RTO, so the sender assumes the path is badly
congested, remembers half the current window as the new threshold, drops
`cwnd` to one segment and restarts slow start.

The phase is set before the window so that the emitted `cwnd_change`
event already carries the new phase.

#### `class Classic(CC)`

Fixed-window sender with no congestion control.

The window stays at `sendWindow` for the entire run: it never grows on
success and never shrinks on loss. Reliability is still honoured — lost
segments are retransmitted — but the sending rate ignores the state of the
network entirely.

Included as a reference point. Run it beside Tahoe or Reno with the same
seed and the value of reacting to congestion becomes visible immediately.

#### `Classic.on_new_ack(self, e, acked, segments_acked = 1)`

Do nothing: a fixed window does not grow.

#### `Classic.on_triple_dup_ack(self, e)`

Retransmit the missing segment without touching the window.

Loss recovery is a reliability mechanism, so it still happens; only the
congestion reaction is absent.

#### `Classic.on_timeout(self, e)`

Do nothing: a fixed window does not shrink.

#### `class SlowStartCA(CC)`

Slow start plus additive-increase congestion avoidance (RFC 5681).

The growth half of Tahoe and Reno, which differ only in how they *shrink*.
Two regimes, separated by `ssthresh`:

- **Slow start** — one extra segment per acknowledgement, which doubles the
  window every round trip. Despite the name this is the fast, exponential
  probe used when the sender has no idea what the path can carry.
- **Congestion avoidance** — `1/cwnd` extra segments per acknowledgement,
  adding roughly one segment per round trip. A cautious linear search near
  the capacity found by the previous loss.

#### `SlowStartCA._grow(self, e)`

Apply one increment of window growth for the current phase.

Crossing `ssthresh` during slow start switches the sender into
congestion avoidance.

#### `SlowStartCA.on_new_ack(self, e, acked, segments_acked = 1)`

Grow the window according to the current phase.

#### `class Tahoe(SlowStartCA)`

TCP Tahoe: fast retransmit, but no fast recovery (Jacobson, 1988).

Tahoe treats both loss signals the same way — duplicate acknowledgements and
timeouts alike drop `cwnd` to one segment and restart slow start. Its one
refinement over a naive sender is fast retransmit: it resends the missing
segment on the third duplicate ACK instead of waiting for the timer.

Collapsing the window on a loss that duplicate ACKs already proved to be
isolated is exactly the pessimism Reno removes.

#### `Tahoe.on_triple_dup_ack(self, e)`

Halve the threshold, collapse the window, resend, and slow-start again.

#### `class Reno(SlowStartCA)`

TCP Reno: fast retransmit plus fast recovery (RFC 5681, RFC 6582).

Duplicate acknowledgements prove that segments are still reaching the
receiver, so the path cannot be badly congested. Reno exploits that: on the
third duplicate it halves the window instead of collapsing it, and enters
*fast recovery* to keep data flowing while the gap is repaired.

The window is inflated by three segments on entry — one for each duplicate
already seen, since each represents a segment that has left the network —
and by one more for every further duplicate. Those inflation steps and the
deflation back to `ssthresh` on the first new acknowledgement happen in the
engine's ACK handler, because they are bookkeeping rather than policy.

A timeout still means slow start: the inherited `CC.on_timeout()` applies.

#### `Reno.on_triple_dup_ack(self, e)`

Halve the window, inflate by three segments, and enter fast recovery.

#### `class Cubic(CC)`

CUBIC congestion control (RFC 9438).

On a path with a large bandwidth-delay product, Reno's one-segment-per-RTT
increase is far too slow to recover after a loss. CUBIC replaces it with a
cubic function of the *elapsed time* since the last congestion event, which
makes growth independent of the round-trip time and therefore fair between
flows with different RTTs:

    W_cubic(t) = C * (t - K)^3 + W_max

`W_max` is the window at the last loss and `K` the time needed to climb back
to it. The shape is the point: growth is fast right after the reduction,
flattens out as it approaches `W_max` (the *concave* region, where the
sender is cautious near the capacity it already knows), then accelerates
again beyond it (the *convex* region, probing for new capacity).

Because that curve can be slower than Reno on short-RTT paths, CUBIC also
tracks what a Reno sender would have done (`W_est`) and uses whichever is
larger — the **Reno-friendly region** of §4.3.

What is implemented: the window function (§4.2), the concave and convex
regions (§4.4, §4.5), the Reno-friendly region (§4.3), multiplicative
decrease computed from `flight_size` (§4.6) and the timeout rules (§4.8).

What is not, and why: **fast convergence** (§4.7) only affects how several
CUBIC flows share a bottleneck, and the RFC says it SHOULD be disabled for a
single flow — the case this simulator models. **HyStart++** (§4.10) is
likewise omitted; plain slow start is the permitted fallback.

#### `Cubic._start_epoch(e)`

Open a new congestion-avoidance stage and pin its cubic curve.

The curve is defined by where the stage begins, so `t_epoch`,
`cwnd_epoch`, `W_max`, `K` and `W_est` are all fixed here, on the first
acknowledgement after entering congestion avoidance.

Which curve applies depends on how the stage was reached. After a
congestion event the sender aims back at the window it lost, so
`W_max` is the window from before the reduction and
`K = cbrt((W_max - cwnd_epoch) / C)` is the climb time to reach it
(§4.2). Entering from slow start there is nothing to climb back to, so
`K = 0` and the sender probes upward from the current window
immediately — which is what §4.10 requires on the first stage, and §4.8
after a timeout.

#### `Cubic._w_cubic(cu, t_s)`

Evaluate `W_cubic(t) = C * (t - K)^3 + W_max` (RFC 9438 §4.2, Figure 1).

- `cu` — the engine's CUBIC state dictionary.
- `t_s` — seconds elapsed since `t_epoch`.

Returns the window the cubic curve calls for at that moment, in segments.

#### `Cubic.on_new_ack(self, e, acked, segments_acked = 1)`

Advance the window along the cubic curve, or along Reno's, whichever leads.

In slow start the behaviour is ordinary exponential growth. In congestion
avoidance three things happen on every acknowledgement:

1. The Reno estimate advances by `ALPHA_CUBIC * segments_acked / cwnd`.
   Once it has climbed back to `cwnd_prior` the factor becomes 1, so the
   estimate then tracks a standard Reno sender (§4.3).
2. The cubic curve is evaluated one round-trip time *ahead*, so the
   window is already correct when the next acknowledgements arrive, and
   the result is clamped to `[cwnd, 1.5 * cwnd]` to bound how much a
   single acknowledgement may open the window (§4.2).
3. Whichever of the two is higher wins. Below `W_max` the growth is
   concave, above it convex; the trace records which, so the two regions
   are visible in the UI.

#### `Cubic.on_triple_dup_ack(self, e)`

Reduce the window by `BETA_CUBIC` and enter fast recovery (RFC 9438 §4.6).

Two details distinguish this from Reno's reaction. The reduction factor
is 0.7 rather than one half, and the new threshold is computed from
`flight_size` — the data actually outstanding — rather than from `cwnd`,
as the RFC requires.

The window in force before the cut is saved as `cwnd_prior`, and the next
congestion-avoidance stage is marked as following a congestion event, so
`_start_epoch()` will aim the cubic curve back at it.

#### `Cubic.on_timeout(self, e)`

Collapse to one segment, but set the threshold with `BETA_CUBIC` (§4.8).

The window reaction matches Reno — a timeout means slow start from one
segment — while the threshold follows CUBIC's own decrease factor and is
again derived from `flight_size` rather than `cwnd`.

The stage that follows is *not* marked as post-congestion: §4.8 and §4.10
require the first congestion-avoidance stage after a timeout to start
with `K = 0`, probing upward from wherever slow start left the window.

---

### `backend/engine/core.py`

Discrete-event simulation core.

Instead of sleeping through a transmission in real time, the engine keeps a
*virtual* clock and a priority queue of things that will happen: a segment is
put on the wire, a segment arrives, an acknowledgement arrives, a timer fires.
It repeatedly takes the earliest pending event, jumps the clock to it, processes
it, and schedules whatever follows. A thirty-second transmission is therefore
computed in a fraction of a second, and the result is a complete trace of
timestamped events rather than an animation that has to be watched.

Everything is deterministic. Loss decisions come from a seeded generator
(`engine.prng`), so a given configuration and seed always produce exactly the
same trace — which is what allows the JavaScript port used by the interactive
page to be verified against this implementation event for event.

The engine also carries no state between requests. A run can be *continued*
because `checkpoint()` serialises everything needed to resume — including the
pending event queue and the generator state — and the client sends that back
with the next request, optionally with different parameters.

#### `class Engine`

One simulated TCP connection over a lossy, delayed path.

The engine owns the virtual clock, the event queue, and both endpoints. The
sender's window policy is delegated to a strategy object from
`engine.congestion`; everything else — transmission, propagation, loss,
acknowledgement, timers — lives here and is identical for all protocols.

**Sender state.** `send_base` is the oldest unacknowledged sequence number
and `next_seq` the next one to send, so `next_seq - send_base` is what is in
flight. Sending is allowed while that stays below the effective window,
which is the smaller of the congestion window and the receiver's advertised
window. `cwnd`, `ssthresh` and `phase` are read and written by the strategy.

**Receiver state.** `expected` is the next in-order sequence number and the
value carried by every acknowledgement, since acknowledgements are
cumulative. Under selective repeat, segments that arrive early are held in
`recv_buffer` until the gap is filled; under go-back-n they are discarded.

**Events.** Two vocabularies coexist and are worth keeping apart. Internally
the queue holds scheduling records — `send`, `data_arrive`, `data_drop`,
`ack_arrive`, `ack_drop`, `rto` — while `events` accumulates the *trace* the
API returns, whose names describe what an observer would see
(`packet_send`, `packet_deliver`, `packet_drop`, `dup_ack`, `cwnd_change`
and so on).

#### `Engine.__init__(self, cfg: Config, seed: int = 1)`

Set up a connection ready to start transmitting.

- `cfg` — validated simulation parameters.
- `seed` — seed for the loss generator; equal seeds reproduce a run
  exactly. `resume()` passes 0 here and then overwrites the generator
  state from the checkpoint.

The initial `ssthresh` is set high on purpose, so a fresh connection
spends its early round trips in slow start rather than starting out in
congestion avoidance.

#### `Engine.eff_window(self)`

Return the effective window: congestion control capped by flow control.

The sender may never have more segments outstanding than the receiver
advertised, however large the congestion window has grown.

#### `Engine.flight_size(self)`

Return how many segments are outstanding (sent but not acknowledged).

CUBIC's multiplicative decrease is defined in terms of this quantity
rather than the congestion window (RFC 9438 §4.6).

#### `Engine.srtt_s(self)`

Return the smoothed round-trip time in seconds.

CUBIC needs an RTT to evaluate its curve one round trip ahead. Before
any measurement exists, the nominal path delay from the configuration
stands in.

#### `Engine.emit(self, etype: str, **payload)`

Append one entry to the trace, stamped with the current virtual time.

- `etype` — event type, one of the names listed in the API's event
  schema.
- `payload` — type-specific fields such as `seq`, `ack` or `value`.

#### `Engine.set_cwnd(self, value, reason = '')`

Update the congestion window, emitting an event when it visibly changes.

The window is fractional — congestion avoidance advances it by `1/cwnd`
per acknowledgement — but a trace entry for every fractional step would
be noise, so an event is emitted only when the integer part moves. The
floor is one segment: a sender must always be able to make progress.

- `value` — the new window in segments.
- `reason` — short tag recorded in the trace (`slow-start`,
  `cong-avoid`, `fast-retransmit`, `cubic-convex`, …) explaining which
  rule produced the change.

#### `Engine.set_phase(self, phase)`

Move the sender to a new phase, emitting an event if it actually changed.

Phases are `slow-start`, `congestion-avoidance` and `fast-recovery`.
Strategies set the phase before the window so that the resulting
`cwnd_change` event already reports the new phase.

#### `Engine.emit_ssthresh(self)`

Record the current slow-start threshold in the trace.

#### `Engine._push(self, t, kind, data)`

Queue an event for virtual time `t`.

A monotonically increasing counter accompanies the timestamp so that
events scheduled for the same instant are processed in the order they
were created. Without it, ordering would depend on how the heap happens
to compare payloads, and runs would stop being reproducible.

#### `Engine._start_timer(self)`

Arm the retransmission timer for the current RTO.

Cancelling entries inside a heap is awkward, so the timer is versioned
instead: every arming bumps `timer_gen`, and an expiry whose generation
no longer matches is ignored as stale.

#### `Engine._stop_timer(self)`

Disarm the timer by invalidating any expiry still queued.

#### `Engine._schedule_send(self, t)`

Ask for a send opportunity at or after `t`, if none is pending.

Requests are collapsed into a single pending opportunity, so the many
places that might open the window (a new acknowledgement, window
inflation, a timeout) cannot queue duplicate sends. The opportunity is
never scheduled before the bottleneck has finished the previous segment.

#### `Engine._transmit(self, seq, retransmit, fast = False)`

Put one segment on the wire and decide its fate.

Whether the segment is lost is drawn here, at transmission time, but the
outcome only becomes visible when it reaches the far end: either a
`data_arrive` or a `data_drop` is queued one propagation delay away.
Deciding early costs nothing and keeps the random sequence tied to the
act of sending, which is what makes traces reproducible.

The send time is recorded so a later acknowledgement can yield an RTT
sample, along with whether this was a retransmission — Karn's algorithm
needs that to reject ambiguous samples.

- `seq` — sequence number being sent.
- `retransmit` — whether this segment has been sent before.
- `fast` — whether this is a fast retransmit, which is reported to the
  trace as `fast_retransmit` rather than `packet_send`.

#### `Engine.fast_retransmit(self)`

Resend the oldest unacknowledged segment.

Called by a strategy when three duplicate acknowledgements have
identified `send_base` as missing.

#### `Engine._handle_send(self)`

Use a send opportunity: transmit one segment if the window allows.

Only one segment goes out per opportunity; if room remains, the next
opportunity is scheduled for when the bottleneck frees up, which is what
spaces segments at the configured bandwidth. When the window is full the
chain stops, and a later acknowledgement restarts it.

#### `Engine._handle_data_arrive(self, seq)`

Deliver a segment to the receiver and send back a cumulative ACK.

An in-order segment advances `expected`, pulling in any buffered
successors that the gap was blocking. An out-of-order segment is
buffered under selective repeat (if it fits in the advertised window) or
dropped under go-back-n.

Either way the receiver acknowledges `expected`, which is what makes
acknowledgements cumulative: when a segment is missing the same value is
repeated, and those duplicates are the sender's loss signal. The ACK may
itself be lost on the way back.

#### `Engine._handle_data_drop(self, seq)`

Record that a segment vanished in transit.

Nothing else happens: a loss is silent by definition, and the sender
only learns of it from duplicate acknowledgements or a timeout.

#### `Engine._handle_ack(self, ack)`

Process an acknowledgement arriving at the sender.

Three cases, distinguished by how the number compares with `send_base`:

**A new acknowledgement** slides the window forward. If the segment it
confirms was never retransmitted, its round trip becomes an RTT sample
(Karn's algorithm rejects the rest). The timer is restarted while data
is still outstanding and stopped otherwise. In fast recovery this ACK
ends the episode, deflating the window to `ssthresh`; otherwise the
strategy decides how the window grows, and is told how many segments
this ACK covered.

**A duplicate** repeats `send_base`, meaning something arrived out of
order. During fast recovery each duplicate inflates the window by one
segment, since a duplicate proves a segment has left the network. Away
from fast recovery, the third duplicate triggers the strategy's loss
reaction.

**A stale acknowledgement** below `send_base` is ignored.

#### `Engine._handle_rto(self, gen)`

Handle expiry of the retransmission timer.

Stale expiries — those whose generation has been superseded, or those
arriving when nothing is outstanding — are discarded.

A real timeout is the strongest loss signal there is, so the strategy
applies its harshest reaction and the timer backs off exponentially.
What is resent depends on the mode: go-back-n rewinds `next_seq` to
`send_base` and retransmits the entire window, while selective repeat
resends only the missing segment. The duplicate counter is cleared,
because the fast-retransmit sequence has been overtaken by the timeout.

- `gen` — the timer generation this expiry belongs to.

#### `Engine.run(self, until_ms: int)`

Drain the event queue until the virtual clock reaches `until_ms`.

The initial window and threshold are recorded first, so a trace always
opens with the sender's starting state, and the first send opportunity
is queued. The loop then repeatedly takes the earliest event, advances
the clock to it and dispatches it, until nothing remains that falls
inside the requested span.

Events still queued beyond that point are deliberately left in place:
they represent segments in flight, and `checkpoint()` carries them over
so a continuation picks the transmission up mid-stride.

- `until_ms` — the virtual time to stop at, in milliseconds.

#### `Engine.checkpoint(self)`

Serialise everything needed to resume this run later.

The result is plain JSON — no objects, no references — and is handed to
the client, which sends it back to continue. That is what keeps the
server stateless: the run's state lives with whoever is watching it, not
in server memory, so nothing has to be tracked between requests.

The snapshot covers more than the obvious window variables. The pending
event queue is included, so segments already in flight keep the fate
that was drawn for them; so is the generator state, so the random
sequence continues rather than restarting; and so is the timer
generation, so a stale expiry stays stale across the boundary.

Sequence numbers are converted to strings in `in_flight` because JSON
object keys must be strings; `resume()` converts them back.

#### `Engine.resume(cls, checkpoint: dict, new_cfg: Config | None = None)`

Rebuild an engine from a checkpoint, optionally under new parameters.

Restoring with the original configuration continues the run exactly as
if it had never stopped — verified by comparing a single long run
against the same run split in two.

Passing `new_cfg` is the interesting case: the continuation obeys the
new parameters from that moment on, while segments already in flight
keep the fate drawn under the old ones. That is what lets the UI switch
protocol or raise the loss rate mid-transmission and watch the sender
adapt.

The trace is intentionally emptied, so a continuation returns only its
own new events; the client appends them to what it already has.

- `checkpoint` — a snapshot produced by `checkpoint()`.
- `new_cfg` — replacement parameters, or `None` to keep the originals.

#### `simulate(config: dict, duration_s: int, seed: int = 1, resume_state: dict | None = None)`

Run or continue a simulation. The engine's public entry point.

Used by the API layer and by the tests. A pure function: the same arguments
always give the same result, and nothing is retained between calls.

- `config` — validated parameters (see `engine.config.validate_config`).
- `duration_s` — how many *additional* seconds of virtual time to simulate.
  On a continuation this extends the run rather than restarting it.
- `seed` — seed for the loss generator; ignored when resuming, since the
  generator state comes from the checkpoint.
- `resume_state` — a checkpoint to continue from, or `None` to start fresh.

Returns a dictionary with `events` (the trace produced by this call),
`checkpoint` (the state needed to continue) and `stats` (cumulative
counters).

---

### `backend/engine/prng.py`

Deterministic pseudo-random number generator.

Loss decisions (which data segments and which ACKs are dropped) must be
reproducible: the same configuration and the same seed have to produce the same
trace, both across runs and across the Python and JavaScript implementations.
Python's :mod:`random` is unsuitable because its state is large and awkward to
serialize, so the engine uses **splitmix64** instead — a small, fast generator
whose entire state is a single 64-bit integer.

That property is what makes a stateless "continue" possible: the generator state
travels inside the checkpoint as an ordinary JSON number, and restoring it
resumes the exact random sequence where it left off.

#### `class PRNG`

splitmix64 pseudo-random generator.

The whole state is one 64-bit integer (`state`), so it serializes into a
checkpoint without any special handling. The algorithm is the standard
splitmix64 mixing function: advance the state by the golden-ratio constant,
then apply two multiply-xorshift rounds.

Instances are not thread-safe, which is irrelevant here — each simulation
run owns its own generator.

#### `PRNG.__init__(self, state: int)`

Seed the generator.

- `state` — the initial seed. Any integer is accepted; it is truncated
  to 64 bits. Equal seeds always yield equal sequences.

#### `PRNG.next_u64(self)`

Advance the generator and return the next 64-bit unsigned integer.

#### `PRNG.chance(self, percent: float)`

Draw a Bernoulli trial and report whether it succeeded.

Consumes exactly one value from the sequence, which is what keeps the
Python and JavaScript engines in lockstep: both call `chance()` at the
same points, in the same order.

- `percent` — success probability expressed in percent (`0`–`100`).

Returns `True` with probability `percent / 100`.

---

### `backend/engine/rto.py`

Adaptive retransmission timer (RFC 6298).

TCP cannot use a fixed retransmission timeout: too short and it floods the
network with needless duplicates, too long and it stalls after a loss. RFC 6298
therefore derives the timeout from measured round-trip times, tracking both a
smoothed average (`SRTT`) and how much the measurements vary (`RTTVAR`):

    RTO = SRTT + max(G, K * RTTVAR)

with `K = 4`, smoothing factors `alpha = 1/8` for `SRTT` and `beta = 1/4` for
`RTTVAR`, and `G` the clock granularity.

Two rules from the standard matter as much as the formula itself. **Karn's
algorithm** forbids taking an RTT sample from a retransmitted segment, since it
is ambiguous which copy an arriving ACK answers; this module cannot detect that
condition on its own, so the engine filters such samples out before calling
`update()`. **Exponential backoff** doubles the timeout every time the timer
fires, so a congested path is not hammered at the original rate.

See also: Jacobson, *Congestion Avoidance and Control* (SIGCOMM 1988), where the
mean-deviation estimator originates, and Karn & Partridge (SIGCOMM 1987).

#### `class RtoEstimator`

Mutable RTO estimator for one sender.

A dataclass so that `dataclasses.asdict()` can drop the whole estimator into
a checkpoint and `RtoEstimator(**d)` can restore it verbatim.

Fields:

- `rto` — the current retransmission timeout in milliseconds. Seeded from
  the `timeout` configuration parameter and then driven by measurements.
- `srtt` — smoothed round-trip time (ms); meaningless until `has_sample`.
- `rttvar` — smoothed round-trip time variation (ms).
- `has_sample` — whether at least one RTT measurement has been taken. The
  first sample is handled by a different formula than later ones.
- `G` — clock granularity in milliseconds; the lower bound on the variation
  term.
- `rto_min`, `rto_max` — clamps applied to every computed timeout.
- `K` — multiplier on `RTTVAR` (4 in RFC 6298).
- `ALPHA`, `BETA` — smoothing factors for `SRTT` and `RTTVAR` (1/8 and 1/4).

#### `RtoEstimator.update(self, r: float)`

Fold one round-trip measurement into the estimate and recompute `rto`.

The first measurement initialises the estimators (`SRTT = R`,
`RTTVAR = R/2`); later ones smooth them exponentially. Note the ordering
mandated by RFC 6298: `RTTVAR` is updated using the *previous* `SRTT`,
before `SRTT` itself moves.

Callers must honour Karn's algorithm and skip samples that come from
retransmitted segments — this method has no way to detect them.

- `r` — the measured round-trip time in milliseconds.

#### `RtoEstimator.backoff(self)`

Double the timeout after the timer expires (exponential backoff).

Applied on every RTO event, so repeated timeouts back off geometrically
until an ACK arrives and `update()` recomputes the timer from fresh
measurements.

#### `RtoEstimator._clamp(self, v: float)`

Confine a candidate timeout to `[rto_min, rto_max]`.
