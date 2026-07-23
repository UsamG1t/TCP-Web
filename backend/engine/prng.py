"""Deterministic pseudo-random number generator.

Loss decisions (which data segments and which ACKs are dropped) must be
reproducible: the same configuration and the same seed have to produce the same
trace, both across runs and across the Python and JavaScript implementations.
Python's :mod:`random` is unsuitable because its state is large and awkward to
serialize, so the engine uses **splitmix64** instead — a small, fast generator
whose entire state is a single 64-bit integer.

That property is what makes a stateless "continue" possible: the generator state
travels inside the checkpoint as an ordinary JSON number, and restoring it
resumes the exact random sequence where it left off.
"""


class PRNG:
    """splitmix64 pseudo-random generator.

    The whole state is one 64-bit integer (`state`), so it serializes into a
    checkpoint without any special handling. The algorithm is the standard
    splitmix64 mixing function: advance the state by the golden-ratio constant,
    then apply two multiply-xorshift rounds.

    Instances are not thread-safe, which is irrelevant here — each simulation
    run owns its own generator.
    """

    MASK = (1 << 64) - 1
    """Bit mask used to keep arithmetic inside 64 bits (Python ints are unbounded)."""

    def __init__(self, state: int):
        """Seed the generator.

        - `state` — the initial seed. Any integer is accepted; it is truncated
          to 64 bits. Equal seeds always yield equal sequences.
        """
        self.state = state & self.MASK

    def next_u64(self) -> int:
        """Advance the generator and return the next 64-bit unsigned integer."""
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        return (z ^ (z >> 31)) & self.MASK

    def chance(self, percent: float) -> bool:
        """Draw a Bernoulli trial and report whether it succeeded.

        Consumes exactly one value from the sequence, which is what keeps the
        Python and JavaScript engines in lockstep: both call `chance()` at the
        same points, in the same order.

        - `percent` — success probability expressed in percent (`0`–`100`).

        Returns `True` with probability `percent / 100`.
        """
        return (self.next_u64() / (1 << 64)) * 100.0 < percent
