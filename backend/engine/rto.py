"""Adaptive retransmission timeout per RFC 6298.

SRTT / RTTVAR smoothed estimators, RTO = SRTT + max(G, K*RTTVAR) with K=4,
alpha=1/8, beta=1/4. Karn's algorithm (skip RTT samples from retransmitted
segments) is enforced by the caller. Exponential backoff on timeout.
"""

from dataclasses import dataclass


@dataclass
class RtoEstimator:
    rto: float                 # current RTO (ms)
    srtt: float = 0.0
    rttvar: float = 0.0
    has_sample: bool = False
    G: float = 1.0             # clock granularity (ms)
    rto_min: float = 200.0
    rto_max: float = 60000.0
    K: int = 4
    ALPHA: float = 1.0 / 8
    BETA: float = 1.0 / 4

    def update(self, r: float) -> None:
        """Incorporate one RTT sample R (ms). (Karn handled by caller.)"""
        if not self.has_sample:
            self.srtt = r
            self.rttvar = r / 2
            self.has_sample = True
        else:
            # RTTVAR must be updated using SRTT *before* SRTT is updated.
            self.rttvar = (1 - self.BETA) * self.rttvar + self.BETA * abs(self.srtt - r)
            self.srtt = (1 - self.ALPHA) * self.srtt + self.ALPHA * r
        self.rto = self._clamp(self.srtt + max(self.G, self.K * self.rttvar))

    def backoff(self) -> None:
        self.rto = self._clamp(self.rto * 2)

    def _clamp(self, v: float) -> float:
        return max(self.rto_min, min(self.rto_max, v))
