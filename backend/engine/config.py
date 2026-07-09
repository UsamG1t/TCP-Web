"""Simulation configuration: the Config dataclass plus a single source of truth
for defaults / valid ranges. Both the /schema endpoint (which drives the frontend
form) and validate_config() read from the same tables below.
"""

from dataclasses import dataclass

VALID_PROTOCOLS = ["classic", "tahoe", "reno", "cubic"]
VALID_RETRANSMIT = ["gobackn", "selective"]

# name -> (default, min, max)
NUMERIC_PARAMS = {
    "packetTime": (2500, 100, 10000),   # one-way data delay (ms)
    "ackTime":    (1500,   50,  5000),   # one-way ACK delay (ms)
    "sendWindow": (4,      1,    64),   # initial cwnd (segments)
    "recvWindow": (8,      1,    64),   # receiver window (flow-control cap)
    "packetLoss": (5,      0,    50),   # % chance a data segment is dropped
    "ackLoss":    (2,      0,    50),   # % chance an ACK is dropped
    "timeout":    (8000, 200, 20000),   # initial RTO (ms)
    "bandwidth":  (10,     1,   100),   # bottleneck rate (segments/sec)
}

DURATION_MIN = 1
DURATION_MAX = 300


@dataclass
class Config:
    packetTime: int = 2500
    ackTime: int = 1500
    sendWindow: int = 4
    recvWindow: int = 8
    protocol: str = "reno"
    packetLoss: float = 5
    ackLoss: float = 2
    timeout: int = 8000
    bandwidth: int = 10
    retransmitMode: str = "gobackn"

    @property
    def serialization_ms(self) -> float:
        return 1000.0 / max(1, self.bandwidth)


def schema() -> dict:
    """Metadata for the frontend to build its form and validate input."""
    return {
        "numeric": {
            name: {"default": d, "min": lo, "max": hi}
            for name, (d, lo, hi) in NUMERIC_PARAMS.items()
        },
        "protocols": VALID_PROTOCOLS,
        "retransmitModes": VALID_RETRANSMIT,
        "duration": {"default": 30, "min": DURATION_MIN, "max": DURATION_MAX},
    }


def validate_config(raw: dict) -> dict:
    """Return a full, defaulted, validated config dict. Raise ValueError on bad input."""
    if not isinstance(raw, dict):
        raise ValueError("config must be an object")

    cfg = {name: d for name, (d, _, _) in NUMERIC_PARAMS.items()}
    cfg["protocol"] = "reno"
    cfg["retransmitMode"] = "gobackn"

    for name, (_, lo, hi) in NUMERIC_PARAMS.items():
        if name in raw:
            val = raw[name]
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"{name} must be a number")
            if val < lo or val > hi:
                raise ValueError(f"{name} must be between {lo} and {hi}")
            cfg[name] = val

    if "protocol" in raw:
        if raw["protocol"] not in VALID_PROTOCOLS:
            raise ValueError(f"protocol must be one of {VALID_PROTOCOLS}")
        cfg["protocol"] = raw["protocol"]

    if "retransmitMode" in raw:
        if raw["retransmitMode"] not in VALID_RETRANSMIT:
            raise ValueError(f"retransmitMode must be one of {VALID_RETRANSMIT}")
        cfg["retransmitMode"] = raw["retransmitMode"]

    return cfg
