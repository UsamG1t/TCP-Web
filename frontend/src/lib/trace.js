// Pure trace processing. No Svelte, no DOM — unit-testable in isolation.
//
// The backend returns a flat list of timestamped events. The player needs two
// derived views:
//   1. flights  — paired send→arrive/drop segments, for the ladder diagram
//   2. timeline — cumulative state (cwnd/ssthresh/phase/stats) sampled at each
//                 event, so we can answer "what did things look like at time t?"

const SEND_TYPES = new Set(["packet_send", "fast_retransmit"]);
const DATA_END = new Set(["packet_deliver", "packet_drop"]);

// ---- flights ------------------------------------------------------------
// A data flight: one segment leaving the sender and either arriving or dropping.
//   { seq, tSend, tEnd, delivered, retransmit, fast }
// An ack flight: one ACK leaving the receiver, arriving or dropping.
//   { ack, tSend, tEnd, delivered }
export function buildFlights(events) {
  const dataFlights = [];
  const ackFlights = [];
  const pendingData = new Map(); // seq -> [flight, ...] FIFO
  const pendingAck = new Map(); // ackValue -> [tSend, ...] FIFO

  const pushMap = (m, k, v) => {
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(v);
  };
  const shiftMap = (m, k) => {
    const q = m.get(k);
    if (!q || q.length === 0) return undefined;
    const v = q.shift();
    if (q.length === 0) m.delete(k);
    return v;
  };

  for (const e of events) {
    switch (e.type) {
      case "packet_send":
      case "fast_retransmit": {
        const f = {
          seq: e.seq,
          tSend: e.t,
          tEnd: null,
          delivered: null,
          retransmit: e.type === "fast_retransmit" || !!e.retransmit,
          fast: e.type === "fast_retransmit",
        };
        dataFlights.push(f);
        pushMap(pendingData, e.seq, f);
        break;
      }
      case "packet_deliver": {
        // deliver is the "success" marker at the receiver; pair it
        const f = shiftMap(pendingData, e.seq);
        if (f) {
          f.tEnd = e.t;
          f.delivered = true;
        }
        break;
      }
      case "packet_drop": {
        const f = shiftMap(pendingData, e.seq);
        if (f) {
          f.tEnd = e.t;
          f.delivered = false;
        }
        break;
      }
      case "ack_send":
        pushMap(pendingAck, e.ack, { tSend: e.t });
        break;
      case "ack_deliver": {
        const s = shiftMap(pendingAck, e.ack);
        if (s) ackFlights.push({ ack: e.ack, tSend: s.tSend, tEnd: e.t, delivered: true });
        break;
      }
      case "ack_drop": {
        const s = shiftMap(pendingAck, e.ack);
        if (s) ackFlights.push({ ack: e.ack, tSend: s.tSend, tEnd: e.t, delivered: false });
        break;
      }
    }
  }

  // any still-pending flights (in flight past the trace end) get an open tEnd
  for (const [, q] of pendingData) for (const f of q) if (f.tEnd === null) f.tEnd = f.tSend;
  return { dataFlights, ackFlights };
}

// ---- state timeline -----------------------------------------------------
// Walk the events once, accumulating state, and record a sample after every
// event. currentState(t) then binary-searches this array.
const EMPTY_STATS = () => ({
  sent: 0, delivered: 0, lost: 0,
  ackSent: 0, ackDelivered: 0, ackLost: 0,
  retransmits: 0, fastRetransmits: 0, timeouts: 0, dupAcks: 0,
});

export function buildTimeline(events, mode = "gobackn") {
  let cwnd = null, ssthresh = null, phase = "slow-start";
  let sendBase = 0, nextSeq = 0;   // sender window pointers (for the seq-space strip)
  const stats = EMPTY_STATS();
  const samples = [];      // { t, cwnd, ssthresh, phase, sendBase, nextSeq, stats }
  const cwndSeries = [];   // { t, value }
  const ssSeries = [];     // { t, value }

  for (const e of events) {
    switch (e.type) {
      case "cwnd_change": cwnd = e.value; phase = e.phase; cwndSeries.push({ t: e.t, value: e.value }); break;
      case "ssthresh_change": ssthresh = e.value; ssSeries.push({ t: e.t, value: e.value }); break;
      case "phase_change": phase = e.phase; break;
      case "packet_send": stats.sent++; if (e.retransmit) stats.retransmits++; nextSeq = Math.max(nextSeq, e.seq + 1); break;
      case "fast_retransmit": stats.sent++; stats.retransmits++; stats.fastRetransmits++; nextSeq = Math.max(nextSeq, e.seq + 1); break;
      case "packet_deliver": stats.delivered++; break;
      case "packet_drop": stats.lost++; break;
      case "ack_send": stats.ackSent++; break;
      case "ack_deliver": stats.ackDelivered++; sendBase = Math.max(sendBase, e.ack); break;
      case "ack_drop": stats.ackLost++; break;
      case "timeout": stats.timeouts++; if (mode === "gobackn") nextSeq = sendBase; break;  // GBN rewinds next_seq
      case "dup_ack": stats.dupAcks++; break;
    }
    samples.push({ t: e.t, cwnd, ssthresh, phase, sendBase, nextSeq, stats: { ...stats } });
  }

  const tEnd = events.length ? events[events.length - 1].t : 0;
  const maxCwnd = cwndSeries.reduce((m, p) => Math.max(m, p.value), 1);
  return { samples, cwndSeries, ssSeries, tEnd, maxCwnd };
}

// last sample at or before t (binary search)
export function stateAt(samples, t) {
  if (!samples.length) return null;
  let lo = 0, hi = samples.length - 1, ans = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (samples[mid].t <= t) { ans = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  return samples[ans];
}

// Combine a fresh trace with an appended continuation (hybrid "continue").
export function concatTraces(a, b) {
  return { events: a.events.concat(b.events), checkpoint: b.checkpoint, stats: b.stats };
}
