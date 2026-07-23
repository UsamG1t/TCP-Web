"""Discrete-event TCP simulation engine.

A self-contained package with no web framework in it, so it can be exercised
directly from a REPL or a test without starting a server. The API layer imports
`simulate()`; everything else is available for scripting and experimentation.

Modules:

- `core` — the event loop, sender, receiver and checkpointing.
- `congestion` — the four congestion-control strategies.
- `rto` — the adaptive retransmission timer (RFC 6298).
- `prng` — the deterministic generator behind reproducible loss.
- `config` — parameters, defaults, ranges and validation.
"""

from .core import simulate, Engine
from .config import Config, schema, validate_config

__all__ = ["simulate", "Engine", "Config", "schema", "validate_config"]
