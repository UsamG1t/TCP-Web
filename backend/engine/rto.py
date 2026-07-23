"""Adaptive retransmission timer (RFC 6298).

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
"""

from dataclasses import dataclass


@dataclass
class RtoEstimator:
    """Mutable RTO estimator for one sender.

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
    """

    rto: float
    srtt: float = 0.0
    rttvar: float = 0.0
    has_sample: bool = False
    G: float = 1.0
    rto_min: float = 200.0
    rto_max: float = 60000.0
    K: int = 4
    ALPHA: float = 1.0 / 8
    BETA: float = 1.0 / 4

    def update(self, r: float) -> None:
        """Fold one round-trip measurement into the estimate and recompute `rto`.

        The first measurement initialises the estimators (`SRTT = R`,
        `RTTVAR = R/2`); later ones smooth them exponentially. Note the ordering
        mandated by RFC 6298: `RTTVAR` is updated using the *previous* `SRTT`,
        before `SRTT` itself moves.

        Callers must honour Karn's algorithm and skip samples that come from
        retransmitted segments — this method has no way to detect them.

        - `r` — the measured round-trip time in milliseconds.
        """
        if not self.has_sample:
            self.srtt = r
            self.rttvar = r / 2
            self.has_sample = True
        else:
            self.rttvar = (1 - self.BETA) * self.rttvar + self.BETA * abs(self.srtt - r)
            self.srtt = (1 - self.ALPHA) * self.srtt + self.ALPHA * r
        self.rto = self._clamp(self.srtt + max(self.G, self.K * self.rttvar))

    def backoff(self) -> None:
        """Double the timeout after the timer expires (exponential backoff).

        Applied on every RTO event, so repeated timeouts back off geometrically
        until an ACK arrives and `update()` recomputes the timer from fresh
        measurements.
        """
        self.rto = self._clamp(self.rto * 2)

    def _clamp(self, v: float) -> float:
        """Confine a candidate timeout to `[rto_min, rto_max]`."""
        return max(self.rto_min, min(self.rto_max, v))
