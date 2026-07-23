"""Simulation parameters: definitions, defaults, ranges and validation.

This module is the single source of truth for what a simulation can be asked to
do. The tables below feed three consumers at once, which is why they live in one
place: the `/schema` endpoint publishes them so the frontend can build its form,
`validate_config()` enforces them on every request, and `Config` carries the
resulting values into the engine.

Adding a numeric parameter is therefore a one-line change to `NUMERIC_PARAMS`
plus a matching field on `Config`; the API schema and the input validation
follow automatically.
"""

from dataclasses import dataclass

VALID_PROTOCOLS = ["classic", "tahoe", "reno", "cubic"]
"""Congestion-control algorithms the engine implements."""

VALID_RETRANSMIT = ["gobackn", "selective"]
"""Retransmission strategies: resend the whole window, or only what was lost."""

NUMERIC_PARAMS = {
    "packetTime": (2500, 100, 10000),
    "ackTime":    (1500,  50,  5000),
    "sendWindow": (4,      1,    64),
    "recvWindow": (8,      1,    64),
    "packetLoss": (5,      0,    50),
    "ackLoss":    (2,      0,    50),
    "timeout":    (8000, 200, 20000),
    "bandwidth":  (10,     1,   100),
}
"""Numeric parameters as `name -> (default, minimum, maximum)`.

- `packetTime` — one-way propagation delay for data segments, in milliseconds.
- `ackTime` — one-way propagation delay for acknowledgements, in milliseconds.
  Together with `packetTime` this sets the nominal round-trip time.
- `sendWindow` — the sender's initial congestion window, in segments. For the
  `classic` protocol it is also the final one, since that window never moves.
- `recvWindow` — the receiver's advertised window, in segments. Acts as a hard
  cap on the effective window (flow control), independent of congestion control.
- `packetLoss` — probability, in percent, that any given data segment is lost.
- `ackLoss` — probability, in percent, that any given acknowledgement is lost.
- `timeout` — the *initial* retransmission timeout in milliseconds. The timer is
  adaptive (see `engine.rto`), so this value only seeds it; it then converges
  toward the path's measured round-trip time.
- `bandwidth` — bottleneck rate in segments per second, which sets how closely
  consecutive segments can be spaced on the wire.
"""

DURATION_MIN = 1
"""Shortest simulation, in seconds of virtual time."""

DURATION_MAX = 300
"""Longest simulation, in seconds of virtual time. Bounds the size of a trace."""


@dataclass
class Config:
    """One simulation's parameters, in the form the engine consumes.

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
    """

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
        """Milliseconds the bottleneck needs to put one segment on the wire.

        This is the spacing between successive transmissions — the simulated
        equivalent of a link's serialization delay — derived from `bandwidth`.
        """
        return 1000.0 / max(1, self.bandwidth)


def schema() -> dict:
    """Describe every parameter so a client can build and pre-validate a form.

    Returned by `GET /schema`. The payload contains the numeric parameters with
    their default, minimum and maximum, the list of protocols, the list of
    retransmission modes, and the accepted range for `duration`.

    Publishing the schema rather than hard-coding it in the frontend keeps the
    two in step: changing a bound here immediately changes what the UI offers.
    """
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
    """Check a client-supplied configuration and fill in what it omitted.

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
    """
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
