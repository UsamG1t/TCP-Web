"""Discrete-event simulation core.

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
"""

from __future__ import annotations
import heapq
import math
from dataclasses import asdict

from .prng import PRNG
from .rto import RtoEstimator
from .config import Config
from .congestion import STRATEGIES


class Engine:
    """One simulated TCP connection over a lossy, delayed path.

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
    """

    def __init__(self, cfg: Config, seed: int = 1):
        """Set up a connection ready to start transmitting.

        - `cfg` — validated simulation parameters.
        - `seed` — seed for the loss generator; equal seeds reproduce a run
          exactly. `resume()` passes 0 here and then overwrites the generator
          state from the checkpoint.

        The initial `ssthresh` is set high on purpose, so a fresh connection
        spends its early round trips in slow start rather than starting out in
        congestion avoidance.
        """
        self.cfg = cfg
        self.cc = STRATEGIES[cfg.protocol]()
        self.prng = PRNG(seed)

        self.now = 0.0
        self._order = 0
        self.heap: list = []

        self.cwnd = float(cfg.sendWindow)
        self.ssthresh = max(cfg.sendWindow * 4, 64)
        self.phase = "slow-start"
        self.send_base = 0
        self.next_seq = 0
        self.in_flight: dict[int, dict] = {}
        self.dup_acks = 0
        self.next_wire_free = 0.0
        self.send_pending = False

        self.rto = RtoEstimator(rto=float(cfg.timeout))
        self.timer_gen = 0
        self.timer_running = False

        # CUBIC's per-stage state (RFC 9438 §4.1.2). It lives on the engine
        # rather than on the strategy so that it lands in the checkpoint and
        # survives a stateless resume.
        self.cubic = {
            "wmax": 0.0,
            "t_epoch": 0.0,
            "cwnd_epoch": 0.0,
            "cwnd_prior": 0.0,
            "w_est": 0.0,
            "k": 0.0,
            "epoch_started": False,
            "after_congestion": False,
        }

        self.events: list[dict] = []
        self.stats = {"sent": 0, "delivered": 0, "lost": 0,
                      "ackSent": 0, "ackDelivered": 0, "ackLost": 0,
                      "retransmits": 0}

        self.expected = 0
        self.recv_buffer: set[int] = set()

    def eff_window(self) -> float:
        """Return the effective window: congestion control capped by flow control.

        The sender may never have more segments outstanding than the receiver
        advertised, however large the congestion window has grown.
        """
        return min(self.cwnd, self.cfg.recvWindow)

    def flight_size(self) -> int:
        """Return how many segments are outstanding (sent but not acknowledged).

        CUBIC's multiplicative decrease is defined in terms of this quantity
        rather than the congestion window (RFC 9438 §4.6).
        """
        return max(self.next_seq - self.send_base, 0)

    def srtt_s(self) -> float:
        """Return the smoothed round-trip time in seconds.

        CUBIC needs an RTT to evaluate its curve one round trip ahead. Before
        any measurement exists, the nominal path delay from the configuration
        stands in.
        """
        ms = self.rto.srtt if self.rto.has_sample else (self.cfg.packetTime + self.cfg.ackTime)
        return ms / 1000.0

    def emit(self, etype: str, **payload) -> None:
        """Append one entry to the trace, stamped with the current virtual time.

        - `etype` — event type, one of the names listed in the API's event
          schema.
        - `payload` — type-specific fields such as `seq`, `ack` or `value`.
        """
        self.events.append({"t": round(self.now, 2), "type": etype, **payload})

    def set_cwnd(self, value, reason=""):
        """Update the congestion window, emitting an event when it visibly changes.

        The window is fractional — congestion avoidance advances it by `1/cwnd`
        per acknowledgement — but a trace entry for every fractional step would
        be noise, so an event is emitted only when the integer part moves. The
        floor is one segment: a sender must always be able to make progress.

        - `value` — the new window in segments.
        - `reason` — short tag recorded in the trace (`slow-start`,
          `cong-avoid`, `fast-retransmit`, `cubic-convex`, …) explaining which
          rule produced the change.
        """
        value = max(1.0, value)
        changed = math.floor(value) != math.floor(self.cwnd)
        self.cwnd = value
        if changed:
            self.emit("cwnd_change", value=round(self.cwnd, 3),
                      phase=self.phase, reason=reason)

    def set_phase(self, phase):
        """Move the sender to a new phase, emitting an event if it actually changed.

        Phases are `slow-start`, `congestion-avoidance` and `fast-recovery`.
        Strategies set the phase before the window so that the resulting
        `cwnd_change` event already reports the new phase.
        """
        if phase != self.phase:
            self.phase = phase
            self.emit("phase_change", phase=phase)

    def emit_ssthresh(self):
        """Record the current slow-start threshold in the trace."""
        self.emit("ssthresh_change", value=round(self.ssthresh, 3))

    def _push(self, t, kind, data):
        """Queue an event for virtual time `t`.

        A monotonically increasing counter accompanies the timestamp so that
        events scheduled for the same instant are processed in the order they
        were created. Without it, ordering would depend on how the heap happens
        to compare payloads, and runs would stop being reproducible.
        """
        heapq.heappush(self.heap, (t, self._order, kind, data))
        self._order += 1

    def _start_timer(self):
        """Arm the retransmission timer for the current RTO.

        Cancelling entries inside a heap is awkward, so the timer is versioned
        instead: every arming bumps `timer_gen`, and an expiry whose generation
        no longer matches is ignored as stale.
        """
        self.timer_gen += 1
        self.timer_running = True
        self._push(self.now + self.rto.rto, "rto", {"gen": self.timer_gen})

    def _stop_timer(self):
        """Disarm the timer by invalidating any expiry still queued."""
        self.timer_gen += 1
        self.timer_running = False

    def _schedule_send(self, t):
        """Ask for a send opportunity at or after `t`, if none is pending.

        Requests are collapsed into a single pending opportunity, so the many
        places that might open the window (a new acknowledgement, window
        inflation, a timeout) cannot queue duplicate sends. The opportunity is
        never scheduled before the bottleneck has finished the previous segment.
        """
        if not self.send_pending:
            self.send_pending = True
            self._push(max(t, self.next_wire_free), "send", {})

    def _transmit(self, seq, retransmit, fast=False):
        """Put one segment on the wire and decide its fate.

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
        """
        self.in_flight[seq] = {"send_time": self.now, "retransmitted": retransmit}
        self.stats["sent"] += 1
        if fast:
            self.emit("fast_retransmit", seq=seq)
        else:
            self.emit("packet_send", seq=seq, retransmit=retransmit)
        if retransmit:
            self.stats["retransmits"] += 1
        lost = self.prng.chance(self.cfg.packetLoss)
        arrive = self.now + self.cfg.packetTime
        self._push(arrive, "data_drop" if lost else "data_arrive", {"seq": seq})
        if lost:
            self.stats["lost"] += 1
        self.next_wire_free = self.now + self.cfg.serialization_ms
        if not self.timer_running:
            self._start_timer()

    def fast_retransmit(self):
        """Resend the oldest unacknowledged segment.

        Called by a strategy when three duplicate acknowledgements have
        identified `send_base` as missing.
        """
        self._transmit(self.send_base, retransmit=True, fast=True)

    def _handle_send(self):
        """Use a send opportunity: transmit one segment if the window allows.

        Only one segment goes out per opportunity; if room remains, the next
        opportunity is scheduled for when the bottleneck frees up, which is what
        spaces segments at the configured bandwidth. When the window is full the
        chain stops, and a later acknowledgement restarts it.
        """
        self.send_pending = False
        if (self.next_seq - self.send_base) < self.eff_window():
            seq = self.next_seq
            self.next_seq += 1
            self._transmit(seq, retransmit=False)
            self._schedule_send(self.next_wire_free)

    def _handle_data_arrive(self, seq):
        """Deliver a segment to the receiver and send back a cumulative ACK.

        An in-order segment advances `expected`, pulling in any buffered
        successors that the gap was blocking. An out-of-order segment is
        buffered under selective repeat (if it fits in the advertised window) or
        dropped under go-back-n.

        Either way the receiver acknowledges `expected`, which is what makes
        acknowledgements cumulative: when a segment is missing the same value is
        repeated, and those duplicates are the sender's loss signal. The ACK may
        itself be lost on the way back.
        """
        self.stats["delivered"] += 1
        self.emit("packet_deliver", seq=seq)
        if seq == self.expected:
            self.expected += 1
            while self.expected in self.recv_buffer:
                self.recv_buffer.discard(self.expected)
                self.expected += 1
        elif seq > self.expected:
            if self.cfg.retransmitMode == "selective" and \
               (seq - self.expected) < self.cfg.recvWindow:
                self.recv_buffer.add(seq)
        ack = self.expected
        self.stats["ackSent"] += 1
        self.emit("ack_send", ack=ack)
        lost = self.prng.chance(self.cfg.ackLoss)
        arrive = self.now + self.cfg.ackTime
        self._push(arrive, "ack_drop" if lost else "ack_arrive", {"ack": ack})
        if lost:
            self.stats["ackLost"] += 1

    def _handle_data_drop(self, seq):
        """Record that a segment vanished in transit.

        Nothing else happens: a loss is silent by definition, and the sender
        only learns of it from duplicate acknowledgements or a timeout.
        """
        self.emit("packet_drop", seq=seq)

    def _handle_ack(self, ack):
        """Process an acknowledgement arriving at the sender.

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
        """
        self.stats["ackDelivered"] += 1
        self.emit("ack_deliver", ack=ack)

        if ack > self.send_base:
            seg = self.in_flight.get(ack - 1)
            if seg and not seg["retransmitted"]:
                self.rto.update(self.now - seg["send_time"])
            segments_acked = ack - self.send_base
            for s in range(self.send_base, ack):
                self.in_flight.pop(s, None)
            self.send_base = ack
            self.dup_acks = 0
            if self.send_base < self.next_seq:
                self._start_timer()
            else:
                self._stop_timer()
            if self.phase == "fast-recovery":
                self.set_cwnd(self.ssthresh, reason="fr-exit")
                self.set_phase("congestion-avoidance")
            else:
                self.cc.on_new_ack(self, ack, segments_acked)
            self._schedule_send(self.now)

        elif ack == self.send_base:
            self.dup_acks += 1
            self.emit("dup_ack", ack=ack, count=self.dup_acks)
            if self.phase == "fast-recovery":
                self.set_cwnd(self.cwnd + 1, reason="fr-inflate")
                self._schedule_send(self.now)
            elif self.dup_acks == 3:
                self.cc.on_triple_dup_ack(self)

    def _handle_rto(self, gen):
        """Handle expiry of the retransmission timer.

        Stale expiries — those whose generation has been superseded, or those
        arriving when nothing is outstanding — are discarded.

        A real timeout is the strongest loss signal there is, so the strategy
        applies its harshest reaction and the timer backs off exponentially.
        What is resent depends on the mode: go-back-n rewinds `next_seq` to
        `send_base` and retransmits the entire window, while selective repeat
        resends only the missing segment. The duplicate counter is cleared,
        because the fast-retransmit sequence has been overtaken by the timeout.

        - `gen` — the timer generation this expiry belongs to.
        """
        if gen != self.timer_gen or self.send_base >= self.next_seq:
            return
        self.emit("timeout", seq=self.send_base)
        self.cc.on_timeout(self)
        self.rto.backoff()
        self.dup_acks = 0
        if self.cfg.retransmitMode == "gobackn":
            for s in [k for k in self.in_flight if k >= self.send_base]:
                self.in_flight.pop(s, None)
            self.next_seq = self.send_base
        else:
            self._transmit(self.send_base, retransmit=True)
        self.timer_running = False
        self._start_timer()
        self._schedule_send(self.now)

    def run(self, until_ms: int) -> None:
        """Drain the event queue until the virtual clock reaches `until_ms`.

        The initial window and threshold are recorded first, so a trace always
        opens with the sender's starting state, and the first send opportunity
        is queued. The loop then repeatedly takes the earliest event, advances
        the clock to it and dispatches it, until nothing remains that falls
        inside the requested span.

        Events still queued beyond that point are deliberately left in place:
        they represent segments in flight, and `checkpoint()` carries them over
        so a continuation picks the transmission up mid-stride.

        - `until_ms` — the virtual time to stop at, in milliseconds.
        """
        self.emit("cwnd_change", value=round(self.cwnd, 3),
                  phase=self.phase, reason="init")
        self.emit_ssthresh()
        self._schedule_send(0.0)
        while self.heap and self.heap[0][0] <= until_ms:
            t, _, kind, data = heapq.heappop(self.heap)
            self.now = t
            if kind == "send":
                self._handle_send()
            elif kind == "data_arrive":
                self._handle_data_arrive(data["seq"])
            elif kind == "data_drop":
                self._handle_data_drop(data["seq"])
            elif kind == "ack_arrive":
                self._handle_ack(data["ack"])
            elif kind == "ack_drop":
                self.emit("ack_drop", ack=data["ack"])
            elif kind == "rto":
                self._handle_rto(data["gen"])

    def checkpoint(self) -> dict:
        """Serialise everything needed to resume this run later.

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
        """
        return {
            "cfg": asdict(self.cfg),
            "prng": self.prng.state,
            "now": self.now,
            "order": self._order,
            "heap": [[t, o, k, d] for (t, o, k, d) in self.heap],
            "cwnd": self.cwnd, "ssthresh": self.ssthresh, "phase": self.phase,
            "send_base": self.send_base, "next_seq": self.next_seq,
            "in_flight": {str(k): v for k, v in self.in_flight.items()},
            "dup_acks": self.dup_acks, "next_wire_free": self.next_wire_free,
            "send_pending": self.send_pending,
            "rto": asdict(self.rto), "timer_gen": self.timer_gen,
            "timer_running": self.timer_running,
            "cubic": dict(self.cubic),
            "expected": self.expected, "recv_buffer": sorted(self.recv_buffer),
            "stats": self.stats,
        }

    @classmethod
    def resume(cls, checkpoint: dict, new_cfg: Config | None = None) -> "Engine":
        """Rebuild an engine from a checkpoint, optionally under new parameters.

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
        """
        cfg = Config(**checkpoint["cfg"]) if new_cfg is None else new_cfg
        e = cls(cfg, seed=0)
        e.prng.state = checkpoint["prng"]
        e.now = checkpoint["now"]
        e._order = checkpoint["order"]
        e.heap = [tuple(x) for x in checkpoint["heap"]]
        heapq.heapify(e.heap)
        e.cwnd = checkpoint["cwnd"]; e.ssthresh = checkpoint["ssthresh"]
        e.phase = checkpoint["phase"]
        e.send_base = checkpoint["send_base"]; e.next_seq = checkpoint["next_seq"]
        e.in_flight = {int(k): v for k, v in checkpoint["in_flight"].items()}
        e.dup_acks = checkpoint["dup_acks"]
        e.next_wire_free = checkpoint["next_wire_free"]
        e.send_pending = checkpoint["send_pending"]
        e.rto = RtoEstimator(**checkpoint["rto"])
        e.timer_gen = checkpoint["timer_gen"]
        e.timer_running = checkpoint["timer_running"]
        e.cubic = dict(checkpoint.get("cubic", e.cubic))
        e.expected = checkpoint["expected"]
        e.recv_buffer = set(checkpoint["recv_buffer"])
        e.stats = checkpoint["stats"]
        e.cc = STRATEGIES[cfg.protocol]()
        e.events = []
        return e


def simulate(config: dict, duration_s: int, seed: int = 1,
             resume_state: dict | None = None) -> dict:
    """Run or continue a simulation. The engine's public entry point.

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
    """
    cfg = Config(**config)
    if resume_state is None:
        eng = Engine(cfg, seed=seed)
        start = 0.0
    else:
        eng = Engine.resume(resume_state, new_cfg=cfg)
        start = eng.now
    eng.run(int(start + duration_s * 1000))
    return {"events": eng.events, "checkpoint": eng.checkpoint(), "stats": eng.stats}
