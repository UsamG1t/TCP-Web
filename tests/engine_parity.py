#!/usr/bin/env python3
"""Verify that the two simulation engines still agree.

The project deliberately keeps one set of rules in two implementations: the
Python engine in `backend/engine`, which serves `/latest` through the API, and
its JavaScript port embedded in `legacy/tcp_simulator.html`, which drives the
interactive page. They are only two views of one model for as long as they
actually behave identically, and nothing about the code enforces that — so this
script checks it.

Both engines are run over a set of scenarios covering every protocol and both
retransmission modes, and the resulting traces are compared event by event,
timestamps included. Any divergence fails the run and prints the first event
where the two disagree.

The JavaScript engine is extracted straight from the shipped HTML rather than
from a separate copy, so what is tested is exactly what a browser would execute.

Requires Python 3 and Node.js. Run from the repository root:

    python3 tests/engine_parity.py
"""

from __future__ import annotations
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY = ROOT / "legacy" / "tcp_simulator.html"

# Boundary between the ported engine and the UI layer inside the bundled page.
UI_MARKER = "// UI layer. Owns the wall clock"

SCENARIOS = {
    "reno_gobackn": (
        {"protocol": "reno", "retransmitMode": "gobackn", "packetLoss": 10,
         "ackLoss": 3, "bandwidth": 12, "packetTime": 300, "ackTime": 150,
         "sendWindow": 2, "recvWindow": 8, "timeout": 3000}, 25, 7),
    "reno_selective": (
        {"protocol": "reno", "retransmitMode": "selective", "packetLoss": 12,
         "ackLoss": 4, "bandwidth": 15, "packetTime": 400, "ackTime": 200,
         "sendWindow": 3, "recvWindow": 16, "timeout": 4000}, 25, 13),
    "tahoe_gobackn": (
        {"protocol": "tahoe", "retransmitMode": "gobackn", "packetLoss": 10,
         "ackLoss": 3, "bandwidth": 12, "packetTime": 300, "ackTime": 150,
         "sendWindow": 2, "recvWindow": 8, "timeout": 3000}, 25, 7),
    "tahoe_selective": (
        {"protocol": "tahoe", "retransmitMode": "selective", "packetLoss": 15,
         "ackLoss": 5, "bandwidth": 8, "packetTime": 600, "ackTime": 300,
         "sendWindow": 1, "recvWindow": 8, "timeout": 2500}, 30, 21),
    "cubic_selective": (
        {"protocol": "cubic", "retransmitMode": "selective", "packetLoss": 6,
         "ackLoss": 2, "bandwidth": 20, "packetTime": 300, "ackTime": 150,
         "sendWindow": 2, "recvWindow": 64, "timeout": 3000}, 30, 5),
    "cubic_long_fat": (
        {"protocol": "cubic", "retransmitMode": "gobackn", "packetLoss": 0.5,
         "ackLoss": 0, "bandwidth": 100, "packetTime": 2500, "ackTime": 1500,
         "sendWindow": 2, "recvWindow": 64, "timeout": 8000}, 90, 11),
    "classic_gobackn": (
        {"protocol": "classic", "retransmitMode": "gobackn", "packetLoss": 8,
         "ackLoss": 2, "bandwidth": 10, "packetTime": 300, "ackTime": 150,
         "sendWindow": 4, "recvWindow": 8, "timeout": 3000}, 20, 3),
    "defaults": ({"protocol": "reno"}, 60, 1),
}

# Fields compared for every event. Timestamps are checked separately, with a
# tolerance, because the two languages round floating point slightly differently.
FIELDS = ("type", "seq", "ack", "count", "phase", "reason", "value")
TIME_TOLERANCE_MS = 0.02


def extract_engine() -> str:
    """Pull the engine half of the bundled page out as an ES module."""
    html = LEGACY.read_text(encoding="utf-8")
    m = re.search(r'<script type="module">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit(f"no <script type=\"module\"> found in {LEGACY}")
    script = m.group(1)
    if UI_MARKER not in script:
        raise SystemExit(
            f"marker {UI_MARKER!r} not found in {LEGACY}.\n"
            "The UI/engine boundary moved; update UI_MARKER in this script."
        )
    engine = script[:script.index(UI_MARKER)]
    if "class Engine" not in engine:
        raise SystemExit("extracted section does not contain the Engine class")
    return engine.replace("class Engine {", "export class Engine {", 1)


def run_js(engine_src: str) -> dict:
    """Run every scenario through the JavaScript engine and return its traces."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "engine.mjs").write_text(engine_src, encoding="utf-8")
        (tmp / "scenarios.json").write_text(
            json.dumps({k: {"cfg": c, "dur": d, "seed": s}
                        for k, (c, d, s) in SCENARIOS.items()}), encoding="utf-8")
        (tmp / "run.mjs").write_text("""
import { Engine } from './engine.mjs';
import { readFileSync } from 'fs';
const cases = JSON.parse(readFileSync(new URL('./scenarios.json', import.meta.url)));
const out = {};
for (const [name, { cfg, dur, seed }] of Object.entries(cases)) {
  const r = new Engine(cfg, seed).runUntil(dur * 1000);
  out[name] = { events: r.events, stats: r.stats };
}
process.stdout.write(JSON.stringify(out));
""", encoding="utf-8")
        proc = subprocess.run([node_bin(), str(tmp / "run.mjs")],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit("the JavaScript engine failed to run:\n" + proc.stderr)
        return json.loads(proc.stdout)


def node_bin() -> str:
    """Locate the Node.js executable, failing with a clear message."""
    for candidate in ("node", "nodejs"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            continue
    raise SystemExit("Node.js is required to run this check but was not found")


def run_python() -> dict:
    """Run every scenario through the Python engine and return its traces."""
    sys.path.insert(0, str(ROOT / "backend"))
    from engine.core import simulate                     # noqa: E402
    return {name: simulate(cfg, dur, seed=seed)
            for name, (cfg, dur, seed) in SCENARIOS.items()}


def compare(name: str, py: list, js: list) -> list[str]:
    """Compare one scenario's traces, returning a list of problems found."""
    problems = []
    if len(py) != len(js):
        problems.append(f"event count differs: Python {len(py)}, JavaScript {len(js)}")
    for i, (a, b) in enumerate(zip(py, js)):
        for f in FIELDS:
            if a.get(f) != b.get(f):
                problems.append(
                    f"event {i} field {f!r} differs: {a.get(f)!r} vs {b.get(f)!r}\n"
                    f"    Python:     {a}\n    JavaScript: {b}")
                return problems
        if abs(a["t"] - b["t"]) > TIME_TOLERANCE_MS:
            problems.append(
                f"event {i} timestamp differs by {abs(a['t'] - b['t'])} ms\n"
                f"    Python:     {a}\n    JavaScript: {b}")
            return problems
    return problems


def main() -> int:
    print("Comparing the Python engine against the JavaScript port\n")
    js_all = run_js(extract_engine())
    py_all = run_python()

    failures = 0
    total_events = 0
    for name in SCENARIOS:
        py_events = py_all[name]["events"]
        js_events = js_all[name]["events"]
        problems = compare(name, py_events, js_events)
        total_events += len(py_events)
        if problems:
            failures += 1
            print(f"  FAIL  {name:18} {len(py_events):5} events")
            for p in problems:
                print(f"        {p}")
        else:
            print(f"  ok    {name:18} {len(py_events):5} events identical")

    print()
    if failures:
        print(f"{failures} of {len(SCENARIOS)} scenarios diverged.")
        print("The two engines have drifted apart; /old and /latest would now "
              "simulate differently.")
        return 1
    print(f"All {len(SCENARIOS)} scenarios identical "
          f"({total_events} events compared). The engines agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
