"""Congestion-control algorithms.

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
"""

BETA_CUBIC = 0.7
"""CUBIC multiplicative-decrease factor (RFC 9438 §4.6).

A CUBIC sender reduces its window to 70% on loss, where Reno halves it — a
gentler cut that, paired with the cubic increase, keeps throughput high on long
fat paths.
"""

C_CUBIC = 0.4
"""CUBIC scaling constant in segments per second cubed (RFC 9438 §4.1.1).

Governs how aggressively the cubic curve grows once it has passed the previous
maximum.
"""

ALPHA_CUBIC = 3 * (1 - BETA_CUBIC) / (1 + BETA_CUBIC)
"""Additive-increase factor for CUBIC's Reno-friendly region (RFC 9438 §4.3).

Derived as `3 * (1 - beta) / (1 + beta)`, approximately 0.53. It makes the
Reno estimate `W_est` grow at the rate a Reno flow would achieve under the same
conditions.
"""


class CC:
    """Interface shared by every congestion-control strategy.

    Subclasses receive the live `Engine` as their first argument and mutate its
    `cwnd`, `ssthresh` and `phase` directly, emitting trace events through the
    engine's helpers. They never transmit or schedule anything themselves; the
    engine does that once the strategy has decided.

    The default `on_timeout()` implements the classic RFC 5681 reaction and is
    inherited by Tahoe and Reno unchanged.
    """

    name = "base"
    """Identifier used as the key in `STRATEGIES` and in the API's protocol list."""

    def on_new_ack(self, e, acked: int, segments_acked: int = 1) -> None:
        """React to an acknowledgement that advanced the sender's window.

        Called only outside fast recovery; while in fast recovery the engine
        handles window deflation itself.

        - `e` — the engine, whose sender state is to be updated.
        - `acked` — the cumulative acknowledgement number just received.
        - `segments_acked` — how many segments this acknowledgement covers.
          Cumulative ACKs can confirm several at once, and CUBIC scales its
          increase by this count (RFC 9438 §4.3).
        """
        raise NotImplementedError

    def on_triple_dup_ack(self, e) -> None:
        """React to the third duplicate acknowledgement for the same segment.

        Three duplicates are TCP's signal that one segment went missing while
        later ones arrived — a loss worth reacting to immediately rather than
        waiting for the timer. Implementations are expected to call
        `e.fast_retransmit()` so the missing segment is resent.
        """
        raise NotImplementedError

    def on_timeout(self, e) -> None:
        """React to expiry of the retransmission timer (RFC 5681 §3.1).

        A timeout is the harshest loss signal available: nothing has been
        acknowledged for a whole RTO, so the sender assumes the path is badly
        congested, remembers half the current window as the new threshold, drops
        `cwnd` to one segment and restarts slow start.

        The phase is set before the window so that the emitted `cwnd_change`
        event already carries the new phase.
        """
        e.ssthresh = max(e.cwnd / 2, 2)
        e.set_phase("slow-start")
        e.set_cwnd(1.0, reason="timeout")
        e.emit_ssthresh()


class Classic(CC):
    """Fixed-window sender with no congestion control.

    The window stays at `sendWindow` for the entire run: it never grows on
    success and never shrinks on loss. Reliability is still honoured — lost
    segments are retransmitted — but the sending rate ignores the state of the
    network entirely.

    Included as a reference point. Run it beside Tahoe or Reno with the same
    seed and the value of reacting to congestion becomes visible immediately.
    """

    name = "classic"

    def on_new_ack(self, e, acked, segments_acked=1):
        """Do nothing: a fixed window does not grow."""
        pass

    def on_triple_dup_ack(self, e):
        """Retransmit the missing segment without touching the window.

        Loss recovery is a reliability mechanism, so it still happens; only the
        congestion reaction is absent.
        """
        e.fast_retransmit()

    def on_timeout(self, e):
        """Do nothing: a fixed window does not shrink."""
        pass


class SlowStartCA(CC):
    """Slow start plus additive-increase congestion avoidance (RFC 5681).

    The growth half of Tahoe and Reno, which differ only in how they *shrink*.
    Two regimes, separated by `ssthresh`:

    - **Slow start** — one extra segment per acknowledgement, which doubles the
      window every round trip. Despite the name this is the fast, exponential
      probe used when the sender has no idea what the path can carry.
    - **Congestion avoidance** — `1/cwnd` extra segments per acknowledgement,
      adding roughly one segment per round trip. A cautious linear search near
      the capacity found by the previous loss.
    """

    def _grow(self, e):
        """Apply one increment of window growth for the current phase.

        Crossing `ssthresh` during slow start switches the sender into
        congestion avoidance.
        """
        if e.phase == "slow-start":
            e.set_cwnd(e.cwnd + 1, reason="slow-start")
            if e.cwnd >= e.ssthresh:
                e.set_phase("congestion-avoidance")
        elif e.phase == "congestion-avoidance":
            e.set_cwnd(e.cwnd + 1.0 / e.cwnd, reason="cong-avoid")

    def on_new_ack(self, e, acked, segments_acked=1):
        """Grow the window according to the current phase."""
        self._grow(e)


class Tahoe(SlowStartCA):
    """TCP Tahoe: fast retransmit, but no fast recovery (Jacobson, 1988).

    Tahoe treats both loss signals the same way — duplicate acknowledgements and
    timeouts alike drop `cwnd` to one segment and restart slow start. Its one
    refinement over a naive sender is fast retransmit: it resends the missing
    segment on the third duplicate ACK instead of waiting for the timer.

    Collapsing the window on a loss that duplicate ACKs already proved to be
    isolated is exactly the pessimism Reno removes.
    """

    name = "tahoe"

    def on_triple_dup_ack(self, e):
        """Halve the threshold, collapse the window, resend, and slow-start again."""
        e.ssthresh = max(e.cwnd / 2, 2)
        e.emit_ssthresh()
        e.set_phase("slow-start")
        e.set_cwnd(1.0, reason="triple-dup-ack")
        e.fast_retransmit()


class Reno(SlowStartCA):
    """TCP Reno: fast retransmit plus fast recovery (RFC 5681, RFC 6582).

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
    """

    name = "reno"

    def on_triple_dup_ack(self, e):
        """Halve the window, inflate by three segments, and enter fast recovery."""
        e.ssthresh = max(e.cwnd / 2, 2)
        e.emit_ssthresh()
        e.set_phase("fast-recovery")
        e.set_cwnd(e.ssthresh + 3, reason="fast-retransmit")
        e.fast_retransmit()


class Cubic(CC):
    """CUBIC congestion control (RFC 9438).

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
    """

    name = "cubic"

    @staticmethod
    def _start_epoch(e):
        """Open a new congestion-avoidance stage and pin its cubic curve.

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
        """
        cu = e.cubic
        cu["t_epoch"] = e.now
        cu["cwnd_epoch"] = e.cwnd
        cu["w_est"] = e.cwnd

        if cu["after_congestion"]:
            cu["wmax"] = cu["cwnd_prior"]
            delta = cu["wmax"] - cu["cwnd_epoch"]
            cu["k"] = (delta / C_CUBIC) ** (1 / 3) if delta > 0 else 0.0
        else:
            cu["wmax"] = e.cwnd
            cu["k"] = 0.0
            cu["cwnd_prior"] = e.cwnd

        cu["after_congestion"] = False
        cu["epoch_started"] = True

    @staticmethod
    def _w_cubic(cu, t_s):
        """Evaluate `W_cubic(t) = C * (t - K)^3 + W_max` (RFC 9438 §4.2, Figure 1).

        - `cu` — the engine's CUBIC state dictionary.
        - `t_s` — seconds elapsed since `t_epoch`.

        Returns the window the cubic curve calls for at that moment, in segments.
        """
        return C_CUBIC * (t_s - cu["k"]) ** 3 + cu["wmax"]

    def on_new_ack(self, e, acked, segments_acked=1):
        """Advance the window along the cubic curve, or along Reno's, whichever leads.

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
        """
        cu = e.cubic

        if e.phase == "slow-start":
            e.set_cwnd(e.cwnd + segments_acked, reason="slow-start")
            if e.cwnd >= e.ssthresh:
                e.set_phase("congestion-avoidance")
                cu["epoch_started"] = False
            return

        if e.phase != "congestion-avoidance":
            return

        if not cu["epoch_started"]:
            self._start_epoch(e)

        t_s = (e.now - cu["t_epoch"]) / 1000.0
        rtt_s = e.srtt_s()

        alpha = 1.0 if cu["w_est"] >= cu["cwnd_prior"] else ALPHA_CUBIC
        cu["w_est"] = cu["w_est"] + alpha * (segments_acked / max(e.cwnd, 1.0))

        w_ahead = self._w_cubic(cu, t_s + rtt_s)
        if w_ahead < e.cwnd:
            target = e.cwnd
        elif w_ahead > 1.5 * e.cwnd:
            target = 1.5 * e.cwnd
        else:
            target = w_ahead

        if cu["w_est"] > e.cwnd and cu["w_est"] >= self._w_cubic(cu, t_s):
            e.set_cwnd(cu["w_est"], reason="cubic-reno-friendly")
        else:
            reason = "cubic-concave" if e.cwnd < cu["wmax"] else "cubic-convex"
            e.set_cwnd(e.cwnd + (target - e.cwnd) / max(e.cwnd, 1.0), reason=reason)

    def on_triple_dup_ack(self, e):
        """Reduce the window by `BETA_CUBIC` and enter fast recovery (RFC 9438 §4.6).

        Two details distinguish this from Reno's reaction. The reduction factor
        is 0.7 rather than one half, and the new threshold is computed from
        `flight_size` — the data actually outstanding — rather than from `cwnd`,
        as the RFC requires.

        The window in force before the cut is saved as `cwnd_prior`, and the next
        congestion-avoidance stage is marked as following a congestion event, so
        `_start_epoch()` will aim the cubic curve back at it.
        """
        cu = e.cubic
        cu["cwnd_prior"] = e.cwnd
        flight = max(e.flight_size(), 1)
        e.ssthresh = max(flight * BETA_CUBIC, 2)
        e.emit_ssthresh()
        e.set_phase("fast-recovery")
        e.set_cwnd(max(e.cwnd * BETA_CUBIC, 2), reason="fast-retransmit")
        cu["after_congestion"] = True
        cu["epoch_started"] = False
        e.fast_retransmit()

    def on_timeout(self, e):
        """Collapse to one segment, but set the threshold with `BETA_CUBIC` (§4.8).

        The window reaction matches Reno — a timeout means slow start from one
        segment — while the threshold follows CUBIC's own decrease factor and is
        again derived from `flight_size` rather than `cwnd`.

        The stage that follows is *not* marked as post-congestion: §4.8 and §4.10
        require the first congestion-avoidance stage after a timeout to start
        with `K = 0`, probing upward from wherever slow start left the window.
        """
        cu = e.cubic
        cu["cwnd_prior"] = e.cwnd
        flight = max(e.flight_size(), 1)
        e.ssthresh = max(flight * BETA_CUBIC, 2)
        e.set_phase("slow-start")
        e.set_cwnd(1.0, reason="timeout")
        e.emit_ssthresh()
        cu["after_congestion"] = False
        cu["epoch_started"] = False


STRATEGIES = {c.name: c for c in (Classic, Tahoe, Reno, Cubic)}
"""Protocol name to strategy class, used by the engine to instantiate one."""
