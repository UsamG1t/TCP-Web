"""Congestion-control strategies behind a common interface.

Each strategy mutates engine state (cwnd / ssthresh / phase); the engine itself
performs the actual (re)transmission. Protocols: classic, tahoe, reno, cubic.

References:
  RFC 5681 — slow start, congestion avoidance, fast retransmit / fast recovery
  RFC 6582 — NewReno fast recovery
  RFC 9438 — CUBIC (Standards Track; obsoletes RFC 8312)
"""

BETA_CUBIC = 0.7      # RFC 9438 §4.6  (multiplicative decrease factor)
C_CUBIC = 0.4         # RFC 9438 §4.1.1 (scaling constant, segments/second^3)
# RFC 9438 §4.3: alpha_cubic = 3 * (1 - beta) / (1 + beta)
ALPHA_CUBIC = 3 * (1 - BETA_CUBIC) / (1 + BETA_CUBIC)   # ~= 0.5294


class CC:
    name = "base"

    def on_new_ack(self, e, acked: int, segments_acked: int = 1) -> None:
        raise NotImplementedError

    def on_triple_dup_ack(self, e) -> None:
        raise NotImplementedError

    def on_timeout(self, e) -> None:
        e.ssthresh = max(e.cwnd / 2, 2)
        e.set_phase("slow-start")             # phase first: cwnd_change carries it
        e.set_cwnd(1.0, reason="timeout")
        e.emit_ssthresh()


class Classic(CC):
    name = "classic"
    # Fixed window: never react to loss; cwnd stays at sendWindow.
    def on_new_ack(self, e, acked, segments_acked=1): pass
    def on_triple_dup_ack(self, e): e.fast_retransmit()   # reliability only
    def on_timeout(self, e): pass                          # window unchanged


class SlowStartCA(CC):
    """Shared slow-start + AIMD congestion avoidance (Tahoe/Reno)."""
    def _grow(self, e):
        if e.phase == "slow-start":
            e.set_cwnd(e.cwnd + 1, reason="slow-start")
            if e.cwnd >= e.ssthresh:
                e.set_phase("congestion-avoidance")
        elif e.phase == "congestion-avoidance":
            e.set_cwnd(e.cwnd + 1.0 / e.cwnd, reason="cong-avoid")

    def on_new_ack(self, e, acked, segments_acked=1):
        self._grow(e)


class Tahoe(SlowStartCA):
    name = "tahoe"

    def on_triple_dup_ack(self, e):
        e.ssthresh = max(e.cwnd / 2, 2)
        e.emit_ssthresh()
        e.set_phase("slow-start")             # phase first: cwnd_change carries it
        e.set_cwnd(1.0, reason="triple-dup-ack")
        e.fast_retransmit()   # Tahoe: retransmit, then slow-start (no fast recovery)


class Reno(SlowStartCA):
    name = "reno"

    def on_triple_dup_ack(self, e):
        e.ssthresh = max(e.cwnd / 2, 2)
        e.emit_ssthresh()
        e.set_phase("fast-recovery")          # phase first: cwnd_change carries it
        e.set_cwnd(e.ssthresh + 3, reason="fast-retransmit")   # inflate window by 3
        e.fast_retransmit()
    # Inflation on further dup-acks and deflate-on-new-ack are handled in the
    # engine's ack handler.


class Cubic(CC):
    """CUBIC per RFC 9438.

    Implements: the cubic window function (Sec. 4.2), the concave/convex regions
    (4.4, 4.5), the Reno-friendly region via W_est (4.3), multiplicative decrease
    based on flight_size (4.6), and the timeout rules (4.8).

    Fast convergence (4.7) is deliberately NOT implemented: it only matters when
    several CUBIC flows share a bottleneck, and 4.7 states it SHOULD be disabled
    for a single flow — exactly the case this simulator models. HyStart++ (4.10)
    is likewise omitted; plain Reno-style slow start is the allowed fallback.
    """
    name = "cubic"

    # ---- epoch bookkeeping (4.2, 4.8, 4.10) ---------------------------
    @staticmethod
    def _start_epoch(e):
        """Begin a congestion-avoidance stage: fix t_epoch, cwnd_epoch, W_max, K, W_est."""
        cu = e.cubic
        cu["t_epoch"] = e.now
        cu["cwnd_epoch"] = e.cwnd
        cu["w_est"] = e.cwnd            # 4.3: W_est starts at cwnd_epoch

        if cu["after_congestion"]:
            # CA entered after a congestion event: probe back toward the old W_max.
            cu["wmax"] = cu["cwnd_prior"]
            # 4.2: K = cbrt((W_max - cwnd_epoch) / C); 0 if cwnd_epoch >= W_max
            delta = cu["wmax"] - cu["cwnd_epoch"]
            cu["k"] = (delta / C_CUBIC) ** (1 / 3) if delta > 0 else 0.0
        else:
            # CA entered from slow start (initial, or the first stage after a
            # timeout): 4.10 / 4.8 both say K = 0 and W_max = cwnd at entry.
            cu["wmax"] = e.cwnd
            cu["k"] = 0.0
            cu["cwnd_prior"] = e.cwnd

        cu["after_congestion"] = False
        cu["epoch_started"] = True

    @staticmethod
    def _w_cubic(cu, t_s):
        """W_cubic(t) = C*(t - K)^3 + W_max   (4.2, Figure 1)."""
        return C_CUBIC * (t_s - cu["k"]) ** 3 + cu["wmax"]

    # ---- ACK handling --------------------------------------------------
    def on_new_ack(self, e, acked, segments_acked=1):
        cu = e.cubic

        if e.phase == "slow-start":
            e.set_cwnd(e.cwnd + segments_acked, reason="slow-start")
            if e.cwnd >= e.ssthresh:
                e.set_phase("congestion-avoidance")
                cu["epoch_started"] = False      # epoch starts on the next ACK
            return

        if e.phase != "congestion-avoidance":
            return

        if not cu["epoch_started"]:
            self._start_epoch(e)

        t_s = (e.now - cu["t_epoch"]) / 1000.0
        rtt_s = e.srtt_s()

        # --- Reno-friendly region (4.3, Figure 4) ---
        alpha = 1.0 if cu["w_est"] >= cu["cwnd_prior"] else ALPHA_CUBIC
        cu["w_est"] = cu["w_est"] + alpha * (segments_acked / max(e.cwnd, 1.0))

        # --- cubic target, looking one RTT ahead, clamped (4.2) ---
        w_ahead = self._w_cubic(cu, t_s + rtt_s)
        if w_ahead < e.cwnd:
            target = e.cwnd
        elif w_ahead > 1.5 * e.cwnd:
            target = 1.5 * e.cwnd
        else:
            target = w_ahead

        if cu["w_est"] > e.cwnd and cu["w_est"] >= self._w_cubic(cu, t_s):
            # Reno-friendly region: the cubic curve is below the Reno estimate.
            e.set_cwnd(cu["w_est"], reason="cubic-reno-friendly")
        else:
            # Concave (cwnd < W_max) or convex (cwnd >= W_max) region — 4.4 / 4.5
            reason = "cubic-concave" if e.cwnd < cu["wmax"] else "cubic-convex"
            e.set_cwnd(e.cwnd + (target - e.cwnd) / max(e.cwnd, 1.0), reason=reason)

    # ---- congestion events ---------------------------------------------
    def on_triple_dup_ack(self, e):
        cu = e.cubic
        cu["cwnd_prior"] = e.cwnd                     # 4.1.2
        # 4.6: reduce based on flight_size, not cwnd
        flight = max(e.flight_size(), 1)
        e.ssthresh = max(flight * BETA_CUBIC, 2)
        e.emit_ssthresh()
        e.set_phase("fast-recovery")          # phase first: cwnd_change carries it
        e.set_cwnd(max(e.cwnd * BETA_CUBIC, 2), reason="fast-retransmit")
        cu["after_congestion"] = True                 # next CA epoch probes toward W_max
        cu["epoch_started"] = False
        e.fast_retransmit()

    def on_timeout(self, e):
        cu = e.cubic
        cu["cwnd_prior"] = e.cwnd
        # 4.8: cwnd collapses like Reno, but ssthresh uses beta_cubic (not 1/2)
        flight = max(e.flight_size(), 1)
        e.ssthresh = max(flight * BETA_CUBIC, 2)
        e.set_phase("slow-start")             # phase first: cwnd_change carries it
        e.set_cwnd(1.0, reason="timeout")
        e.emit_ssthresh()
        # The first CA stage after a timeout uses K = 0 and W_max = cwnd at entry.
        cu["after_congestion"] = False
        cu["epoch_started"] = False


STRATEGIES = {c.name: c for c in (Classic, Tahoe, Reno, Cubic)}
