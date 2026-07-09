"""Deterministic PRNG (splitmix64). State is a single 64-bit int → JSON-clean,
so it can be serialized into a checkpoint and restored exactly (reproducible runs
and reproducible "continue")."""


class PRNG:
    MASK = (1 << 64) - 1

    def __init__(self, state: int):
        self.state = state & self.MASK

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        return (z ^ (z >> 31)) & self.MASK

    def chance(self, percent: float) -> bool:
        """True with probability percent/100."""
        return (self.next_u64() / (1 << 64)) * 100.0 < percent
