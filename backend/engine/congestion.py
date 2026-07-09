"""Congestion-control strategies behind a common interface.

Each strategy mutates engine state (cwnd / ssthresh / phase); the engine itself
performs the actual (re)transmission. Protocols: classic, tahoe, reno, cubic.

NOTE: CUBIC's growth uses the cubic function of RFC 9438 (C=0.4, beta=0.7) but
does NOT yet model the Reno-friendly region — it's an honest-shape simplification.
"""


class CC:
    name = "base"

    def on_new_ack(self, e, acked: int) -> None:
        raise NotImplementedError

    def on_triple_dup_ack(self, e) -> None:
        raise NotImplementedError

    def on_timeout(self, e) -> None:
        e.ssthresh = max(e.cwnd / 2, 2)
        e.set_cwnd(1.0, reason="timeout")
        e.set_phase("slow-start")
        e.emit_ssthresh()


class Classic(CC):
    name = "classic"
    # Fixed window: never react to loss; cwnd stays at sendWindow.
    def on_new_ack(self, e, acked): pass
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

    def on_new_ack(self, e, acked):
        self._grow(e)


class Tahoe(SlowStartCA):
    name = "tahoe"

    def on_triple_dup_ack(self, e):
        e.ssthresh = max(e.cwnd / 2, 2)
        e.emit_ssthresh()
        e.set_cwnd(1.0, reason="triple-dup-ack")
        e.set_phase("slow-start")
        e.fast_retransmit()   # Tahoe: retransmit, then slow-start (no fast recovery)


class Reno(SlowStartCA):
    name = "reno"

    def on_triple_dup_ack(self, e):
        e.ssthresh = max(e.cwnd / 2, 2)
        e.emit_ssthresh()
        e.set_cwnd(e.ssthresh + 3, reason="fast-retransmit")   # inflate window by 3
        e.set_phase("fast-recovery")
        e.fast_retransmit()
    # Inflation on further dup-acks and deflate-on-new-ack are handled in the
    # engine's ack handler.


class Cubic(SlowStartCA):
    name = "cubic"
    C = 0.4
    BETA_CUBIC = 0.7   # multiplicative decrease factor

    def on_new_ack(self, e, acked):
        if e.phase == "slow-start":
            e.set_cwnd(e.cwnd + 1, reason="slow-start")
            if e.cwnd >= e.ssthresh:
                e.set_phase("congestion-avoidance")
                e.cubic_wmax = e.cwnd
                e.cubic_epoch = e.now
        elif e.phase == "congestion-avoidance":
            t = (e.now - e.cubic_epoch) / 1000.0            # seconds since epoch
            wmax = max(e.cubic_wmax, 1.0)
            k = (wmax * (1 - self.BETA_CUBIC) / self.C) ** (1 / 3)
            target = self.C * (t - k) ** 3 + wmax
            step = max((target - e.cwnd) / max(e.cwnd, 1.0), 1.0 / e.cwnd)
            e.set_cwnd(e.cwnd + step, reason="cubic")

    def on_triple_dup_ack(self, e):
        e.cubic_wmax = e.cwnd
        e.ssthresh = max(e.cwnd * self.BETA_CUBIC, 2)
        e.emit_ssthresh()
        e.set_cwnd(e.ssthresh, reason="fast-retransmit")
        e.set_phase("fast-recovery")
        e.cubic_epoch = e.now
        e.fast_retransmit()


STRATEGIES = {c.name: c for c in (Classic, Tahoe, Reno, Cubic)}
