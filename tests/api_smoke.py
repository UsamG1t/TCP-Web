#!/usr/bin/env python3
"""Exercise the REST API end to end, without starting a server.

Uses Flask's test client, so the whole surface is checked in-process: the
endpoints answer, a simulation runs, a checkpoint resumes a run at the right
point, and every validation path returns the status it should.

The continuation check is the one worth having. It is easy to break the
stateless-resume contract while refactoring — the checkpoint has to carry the
pending event queue, the generator state and the timer generation, and if any of
those is dropped the API still answers 200 and simply returns a wrong trace.
Verifying that the continuation starts where the first run ended catches that.

Run from the repository root:

    python3 tests/api_smoke.py
"""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import app                                       # noqa: E402

CONFIG = {"protocol": "reno", "packetLoss": 8, "bandwidth": 10,
          "packetTime": 300, "ackTime": 150, "sendWindow": 2}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Record one assertion and report it."""
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}: {detail}")
        print(f"  FAIL  {label}  {detail}")


def main() -> int:
    client = app.test_client()

    print("Endpoints\n")
    r = client.get("/health")
    check("GET /health returns ok", r.status_code == 200 and r.json.get("status") == "ok",
          f"status {r.status_code}, body {r.json}")

    r = client.get("/schema")
    schema = r.json or {}
    check("GET /schema returns 200", r.status_code == 200, f"status {r.status_code}")
    check("schema lists the four protocols",
          schema.get("protocols") == ["classic", "tahoe", "reno", "cubic"],
          str(schema.get("protocols")))
    check("schema describes every numeric parameter",
          set(schema.get("numeric", {})) == {
              "packetTime", "ackTime", "sendWindow", "recvWindow",
              "packetLoss", "ackLoss", "timeout", "bandwidth"},
          str(sorted(schema.get("numeric", {}))))

    print("\nSimulation\n")
    r = client.post("/simulate", json={"config": CONFIG, "duration": 10, "seed": 42})
    first = r.json or {}
    check("POST /simulate returns 200", r.status_code == 200, f"status {r.status_code}")
    check("response carries events, checkpoint and stats",
          all(k in first for k in ("events", "checkpoint", "stats")),
          str(sorted(first)))
    check("the trace is non-empty", len(first.get("events", [])) > 0)
    check("a run is reproducible for a given seed",
          client.post("/simulate", json={"config": CONFIG, "duration": 10, "seed": 42}
                      ).json["events"] == first["events"])

    print("\nContinuation\n")
    end_of_first = first["checkpoint"]["now"]
    r = client.post("/simulate", json={
        "config": CONFIG, "duration": 10, "resume_state": first["checkpoint"]})
    second = r.json or {}
    check("continuing a run returns 200", r.status_code == 200, f"status {r.status_code}")
    events = second.get("events", [])
    check("the continuation is non-empty", len(events) > 0)
    # The first two events restate the sender's initial condition; the third is
    # the first thing that actually happens in the continued run.
    if len(events) > 2:
        resumed_at = events[2]["t"]
        check("the continuation starts where the first run ended",
              resumed_at >= end_of_first,
              f"resumed at {resumed_at}, first run ended at {end_of_first}")
    check("continuing accepts different parameters",
          client.post("/simulate", json={
              "config": {**CONFIG, "protocol": "cubic", "packetLoss": 20},
              "duration": 5, "resume_state": first["checkpoint"]}).status_code == 200)

    print("\nValidation\n")
    for label, body, expected in [
        ("unknown protocol is rejected", {"config": {"protocol": "bbr"}}, 400),
        ("out-of-range value is rejected", {"config": {"packetLoss": 999}}, 400),
        ("boolean for a number is rejected", {"config": {"packetLoss": True}}, 400),
        ("out-of-range duration is rejected", {"config": {}, "duration": 9999}, 400),
        ("non-integer seed is rejected", {"config": {}, "seed": "x"}, 400),
        ("malformed resume state is rejected", {"config": {}, "resume_state": "nope"}, 400),
        ("unusable checkpoint is rejected", {"config": {}, "resume_state": {"bad": 1}}, 400),
        ("an empty body uses defaults", {}, 200),
    ]:
        r = client.post("/simulate", json=body)
        check(label, r.status_code == expected, f"got {r.status_code}, expected {expected}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All API checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
