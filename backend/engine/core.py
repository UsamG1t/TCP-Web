"""Discrete-event simulation core.

Virtual-time event queue drives sender / receiver / loss / detection. A run
computes instantly and returns an event trace plus a fully serializable
checkpoint (including the pending event queue and PRNG state) so a run can be
continued later — possibly with new parameters (the "hybrid" model).
"""

from __future__ import annotations
import heapq
import math
from dataclasses import asdict

from .prng import PRNG
from .rto import RtoEstimator
from .config import Config
from .congestion import STRATEGIES


class Engine:
    def __init__(self, cfg: Config, seed: int = 1):
        self.cfg = cfg
        self.cc = STRATEGIES[cfg.protocol]()
        self.prng = PRNG(seed)

        # virtual clock + event heap: (time, order, kind, data)
        self.now = 0.0
        self._order = 0
        self.heap: list = []

        # sender state
        self.cwnd = float(cfg.sendWindow)
        self.ssthresh = max(cfg.sendWindow * 4, 64)
        self.phase = "slow-start"
        self.send_base = 0
        self.next_seq = 0
        self.in_flight: dict[int, dict] = {}   # seq -> {send_time, retransmitted}
        self.dup_acks = 0
        self.next_wire_free = 0.0
        self.send_pending = False

        # RTO timer
        self.rto = RtoEstimator(rto=float(cfg.timeout))
        self.timer_gen = 0
        self.timer_running = False

        # CUBIC state (RFC 9438 §4.1.2). Kept on the engine so it lands in the
        # checkpoint and survives a stateless resume.
        self.cubic = {
            "wmax": 0.0,          # W_max
            "t_epoch": 0.0,       # t_epoch (ms, virtual)
            "cwnd_epoch": 0.0,    # cwnd at the start of the current CA stage
            "cwnd_prior": 0.0,    # cwnd when ssthresh was last set
            "w_est": 0.0,         # W_est (Reno-friendly estimate)
            "k": 0.0,             # K
            "epoch_started": False,
            "after_congestion": False,   # next CA epoch follows a congestion event
        }

        # output + stats
        self.events: list[dict] = []
        self.stats = {"sent": 0, "delivered": 0, "lost": 0,
                      "ackSent": 0, "ackDelivered": 0, "ackLost": 0,
                      "retransmits": 0}

        # receiver
        self.expected = 0
        self.recv_buffer: set[int] = set()

    # ---- helpers -------------------------------------------------------
    def eff_window(self) -> float:
        return min(self.cwnd, self.cfg.recvWindow)

    def flight_size(self) -> int:
        """Segments sent but not yet acknowledged (RFC 9438 §4.6 uses this)."""
        return max(self.next_seq - self.send_base, 0)

    def srtt_s(self) -> float:
        """Smoothed RTT in seconds; falls back to the nominal path RTT."""
        ms = self.rto.srtt if self.rto.has_sample else (self.cfg.packetTime + self.cfg.ackTime)
        return ms / 1000.0

    def emit(self, etype: str, **payload) -> None:
        self.events.append({"t": round(self.now, 2), "type": etype, **payload})

    def set_cwnd(self, value, reason=""):
        value = max(1.0, value)
        changed = math.floor(value) != math.floor(self.cwnd)
        self.cwnd = value
        if changed:
            self.emit("cwnd_change", value=round(self.cwnd, 3),
                      phase=self.phase, reason=reason)

    def set_phase(self, phase):
        if phase != self.phase:
            self.phase = phase
            self.emit("phase_change", phase=phase)

    def emit_ssthresh(self):
        self.emit("ssthresh_change", value=round(self.ssthresh, 3))

    def _push(self, t, kind, data):
        heapq.heappush(self.heap, (t, self._order, kind, data))
        self._order += 1

    # ---- RTO timer -----------------------------------------------------
    def _start_timer(self):
        self.timer_gen += 1
        self.timer_running = True
        self._push(self.now + self.rto.rto, "rto", {"gen": self.timer_gen})

    def _stop_timer(self):
        self.timer_gen += 1
        self.timer_running = False

    # ---- sending -------------------------------------------------------
    def _schedule_send(self, t):
        if not self.send_pending:
            self.send_pending = True
            self._push(max(t, self.next_wire_free), "send", {})

    def _transmit(self, seq, retransmit, fast=False):
        self.in_flight[seq] = {"send_time": self.now, "retransmitted": retransmit}
        self.stats["sent"] += 1
        if fast:
            self.emit("fast_retransmit", seq=seq)
        else:
            self.emit("packet_send", seq=seq, retransmit=retransmit)
        if retransmit:
            self.stats["retransmits"] += 1
        lost = self.prng.chance(self.cfg.packetLoss)
        arrive = self.now + self.cfg.packetTime
        self._push(arrive, "data_drop" if lost else "data_arrive", {"seq": seq})
        if lost:
            self.stats["lost"] += 1
        self.next_wire_free = self.now + self.cfg.serialization_ms
        if not self.timer_running:
            self._start_timer()

    def fast_retransmit(self):
        """Retransmit the oldest unacked segment (triple-dup-ack)."""
        self._transmit(self.send_base, retransmit=True, fast=True)

    def _handle_send(self):
        self.send_pending = False
        if (self.next_seq - self.send_base) < self.eff_window():
            seq = self.next_seq
            self.next_seq += 1
            self._transmit(seq, retransmit=False)
            self._schedule_send(self.next_wire_free)

    # ---- receiver ------------------------------------------------------
    def _handle_data_arrive(self, seq):
        self.stats["delivered"] += 1
        self.emit("packet_deliver", seq=seq)
        if seq == self.expected:
            self.expected += 1
            while self.expected in self.recv_buffer:
                self.recv_buffer.discard(self.expected)
                self.expected += 1
        elif seq > self.expected:
            if self.cfg.retransmitMode == "selective" and \
               (seq - self.expected) < self.cfg.recvWindow:
                self.recv_buffer.add(seq)
            # go-back-n: discard out-of-order
        ack = self.expected
        self.stats["ackSent"] += 1
        self.emit("ack_send", ack=ack)
        lost = self.prng.chance(self.cfg.ackLoss)
        arrive = self.now + self.cfg.ackTime
        self._push(arrive, "ack_drop" if lost else "ack_arrive", {"ack": ack})
        if lost:
            self.stats["ackLost"] += 1

    def _handle_data_drop(self, seq):
        self.emit("packet_drop", seq=seq)

    # ---- ack handling --------------------------------------------------
    def _handle_ack(self, ack):
        self.stats["ackDelivered"] += 1
        self.emit("ack_deliver", ack=ack)

        if ack > self.send_base:                       # new (cumulative) ACK
            seg = self.in_flight.get(ack - 1)
            if seg and not seg["retransmitted"]:       # Karn: no sample on retransmits
                self.rto.update(self.now - seg["send_time"])
            segments_acked = ack - self.send_base      # RFC 9438 needs this (Fig. 4)
            for s in range(self.send_base, ack):
                self.in_flight.pop(s, None)
            self.send_base = ack
            self.dup_acks = 0
            if self.send_base < self.next_seq:
                self._start_timer()
            else:
                self._stop_timer()
            if self.phase == "fast-recovery":          # Reno/CUBIC exit fast recovery
                self.set_cwnd(self.ssthresh, reason="fr-exit")
                self.set_phase("congestion-avoidance")
            else:
                self.cc.on_new_ack(self, ack, segments_acked)
            self._schedule_send(self.now)

        elif ack == self.send_base:                    # duplicate ACK
            self.dup_acks += 1
            self.emit("dup_ack", ack=ack, count=self.dup_acks)
            if self.phase == "fast-recovery":
                self.set_cwnd(self.cwnd + 1, reason="fr-inflate")
                self._schedule_send(self.now)
            elif self.dup_acks == 3:
                self.cc.on_triple_dup_ack(self)
        # ack < send_base: stale, ignore

    def _handle_rto(self, gen):
        if gen != self.timer_gen or self.send_base >= self.next_seq:
            return
        self.emit("timeout", seq=self.send_base)
        self.cc.on_timeout(self)
        self.rto.backoff()
        self.dup_acks = 0
        if self.cfg.retransmitMode == "gobackn":
            for s in [k for k in self.in_flight if k >= self.send_base]:
                self.in_flight.pop(s, None)
            self.next_seq = self.send_base            # rewind: resend the window
        else:
            self._transmit(self.send_base, retransmit=True)
        self.timer_running = False
        self._start_timer()
        self._schedule_send(self.now)

    # ---- main loop -----------------------------------------------------
    def run(self, until_ms: int) -> None:
        self.emit("cwnd_change", value=round(self.cwnd, 3),
                  phase=self.phase, reason="init")
        self.emit_ssthresh()
        self._schedule_send(0.0)
        while self.heap and self.heap[0][0] <= until_ms:
            t, _, kind, data = heapq.heappop(self.heap)
            self.now = t
            if kind == "send":
                self._handle_send()
            elif kind == "data_arrive":
                self._handle_data_arrive(data["seq"])
            elif kind == "data_drop":
                self._handle_data_drop(data["seq"])
            elif kind == "ack_arrive":
                self._handle_ack(data["ack"])
            elif kind == "ack_drop":
                self.emit("ack_drop", ack=data["ack"])
            elif kind == "rto":
                self._handle_rto(data["gen"])

    # ---- checkpoint (stateless resume) --------------------------------
    def checkpoint(self) -> dict:
        return {
            "cfg": asdict(self.cfg),
            "prng": self.prng.state,
            "now": self.now,
            "order": self._order,
            "heap": [[t, o, k, d] for (t, o, k, d) in self.heap],
            "cwnd": self.cwnd, "ssthresh": self.ssthresh, "phase": self.phase,
            "send_base": self.send_base, "next_seq": self.next_seq,
            "in_flight": {str(k): v for k, v in self.in_flight.items()},
            "dup_acks": self.dup_acks, "next_wire_free": self.next_wire_free,
            "send_pending": self.send_pending,
            "rto": asdict(self.rto), "timer_gen": self.timer_gen,
            "timer_running": self.timer_running,
            "cubic": dict(self.cubic),
            "expected": self.expected, "recv_buffer": sorted(self.recv_buffer),
            "stats": self.stats,
        }

    @classmethod
    def resume(cls, checkpoint: dict, new_cfg: Config | None = None) -> "Engine":
        cfg = Config(**checkpoint["cfg"]) if new_cfg is None else new_cfg
        e = cls(cfg, seed=0)
        e.prng.state = checkpoint["prng"]
        e.now = checkpoint["now"]
        e._order = checkpoint["order"]
        e.heap = [tuple(x) for x in checkpoint["heap"]]
        heapq.heapify(e.heap)
        e.cwnd = checkpoint["cwnd"]; e.ssthresh = checkpoint["ssthresh"]
        e.phase = checkpoint["phase"]
        e.send_base = checkpoint["send_base"]; e.next_seq = checkpoint["next_seq"]
        e.in_flight = {int(k): v for k, v in checkpoint["in_flight"].items()}
        e.dup_acks = checkpoint["dup_acks"]
        e.next_wire_free = checkpoint["next_wire_free"]
        e.send_pending = checkpoint["send_pending"]
        e.rto = RtoEstimator(**checkpoint["rto"])
        e.timer_gen = checkpoint["timer_gen"]
        e.timer_running = checkpoint["timer_running"]
        e.cubic = dict(checkpoint.get("cubic", e.cubic))
        e.expected = checkpoint["expected"]
        e.recv_buffer = set(checkpoint["recv_buffer"])
        e.stats = checkpoint["stats"]
        e.cc = STRATEGIES[cfg.protocol]()
        e.events = []
        return e


def simulate(config: dict, duration_s: int, seed: int = 1,
             resume_state: dict | None = None) -> dict:
    """Public entry point used by the Flask layer.

    config       : validated config dict
    duration_s   : how many *additional* seconds to simulate
    resume_state : a checkpoint from a previous call (or None for a fresh run)
    """
    cfg = Config(**config)
    if resume_state is None:
        eng = Engine(cfg, seed=seed)
        start = 0.0
    else:
        eng = Engine.resume(resume_state, new_cfg=cfg)
        start = eng.now
    eng.run(int(start + duration_s * 1000))
    return {"events": eng.events, "checkpoint": eng.checkpoint(), "stats": eng.stats}
