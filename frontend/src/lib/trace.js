/**
 * Trace processing: turning the backend's event list into what the UI draws.
 *
 * The API returns a flat, chronological list of events. That is the right shape
 * to transmit but the wrong shape to render, because every view needs something
 * different: the ladder diagram needs each packet's departure *and* arrival
 * paired into a single line to draw, while the readouts need the cumulative
 * state at whatever instant the playhead sits on.
 *
 * This module derives both, in one pass each, so playback itself stays cheap —
 * during animation nothing here runs again; the player only looks things up.
 *
 * Deliberately free of Svelte and of the DOM, so it can be unit-tested on its
 * own against a trace captured from the backend.
 */

/**
 * One data segment's journey from sender to receiver.
 *
 * @typedef {Object} DataFlight
 * @property {number} seq Sequence number carried by the segment.
 * @property {number} tSend Virtual time it left the sender, in milliseconds.
 * @property {number} tEnd Virtual time it arrived or was lost.
 * @property {boolean|null} delivered `true` if it arrived, `false` if it was lost.
 * @property {boolean} retransmit Whether this was a repeat transmission.
 * @property {boolean} fast Whether it was a fast retransmit, triggered by
 *   duplicate acknowledgements rather than by the timer.
 */

/**
 * One acknowledgement's journey back from receiver to sender.
 *
 * @typedef {Object} AckFlight
 * @property {number} ack The cumulative acknowledgement number.
 * @property {number} tSend Virtual time the receiver sent it.
 * @property {number} tEnd Virtual time it arrived or was lost.
 * @property {boolean} delivered Whether it reached the sender.
 */

/**
 * The complete connection state immediately after one event.
 *
 * @typedef {Object} Sample
 * @property {number} t Virtual time of the event, in milliseconds.
 * @property {number|null} cwnd Congestion window in segments.
 * @property {number|null} ssthresh Slow-start threshold in segments.
 * @property {string} phase One of `slow-start`, `congestion-avoidance`, `fast-recovery`.
 * @property {number} sendBase Oldest unacknowledged sequence number.
 * @property {number} nextSeq Next sequence number the sender will use.
 * @property {Object} stats Cumulative counters up to this point.
 */

/**
 * Pair send events with their outcomes, producing one record per journey.
 *
 * The ladder diagram draws a line per packet, which needs both endpoints — but
 * the trace reports departure and arrival as separate events, possibly far
 * apart. This walks the trace once, holding each departure until its outcome
 * appears.
 *
 * Sequence numbers repeat when a segment is retransmitted, so pending
 * departures are held in per-sequence FIFO queues: the first outcome for a given
 * number belongs to the first transmission still waiting for one.
 *
 * Anything still airborne when the trace ends is given a zero-length flight, so
 * a partial trace never yields a line with no end.
 *
 * @param {Array<Object>} events The trace as returned by `POST /simulate`.
 * @returns {{dataFlights: DataFlight[], ackFlights: AckFlight[]}} Journeys in
 *   both directions, in departure order.
 */
export function buildFlights(events) {
  const dataFlights = [];
  const ackFlights = [];
  const pendingData = new Map();
  const pendingAck = new Map();

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

  for (const [, q] of pendingData) for (const f of q) if (f.tEnd === null) f.tEnd = f.tSend;
  return { dataFlights, ackFlights };
}

/** Build a fresh set of cumulative counters, all at zero. */
const EMPTY_STATS = () => ({
  sent: 0, delivered: 0, lost: 0,
  ackSent: 0, ackDelivered: 0, ackLost: 0,
  retransmits: 0, fastRetransmits: 0, timeouts: 0, dupAcks: 0,
});

/**
 * Replay the trace once, recording the full connection state after every event.
 *
 * Scrubbing has to answer "what did things look like at time t?" instantly and
 * for arbitrary t, so rather than recomputing on demand the answer is
 * precomputed for every event and then found by binary search (see `stateAt`).
 * One sample per event keeps the array aligned with the trace and makes lookups
 * exact rather than interpolated.
 *
 * The window pointers are reconstructed rather than read: the backend does not
 * put `sendBase` and `nextSeq` in the trace, but they follow from it — an
 * arriving acknowledgement is by definition the new `sendBase`, and the highest
 * sequence number sent so far gives `nextSeq`. The one subtlety is a timeout
 * under go-back-n, which rewinds the sender, so `nextSeq` must be pulled back to
 * `sendBase` to match. That is why the retransmission mode has to be passed in.
 *
 * @param {Array<Object>} events The trace as returned by `POST /simulate`.
 * @param {string} [mode="gobackn"] Retransmission mode, `gobackn` or `selective`.
 * @returns {{samples: Sample[], cwndSeries: Array<Object>, ssSeries: Array<Object>,
 *   tEnd: number, maxCwnd: number}} Per-event samples, the two series plotted by
 *   the window chart, the end of the trace, and the peak window used to scale
 *   that chart's axis.
 */
export function buildTimeline(events, mode = "gobackn") {
  let cwnd = null, ssthresh = null, phase = "slow-start";
  let sendBase = 0, nextSeq = 0;
  const stats = EMPTY_STATS();
  const samples = [];
  const cwndSeries = [];
  const ssSeries = [];

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
      case "timeout": stats.timeouts++; if (mode === "gobackn") nextSeq = sendBase; break;
      case "dup_ack": stats.dupAcks++; break;
    }
    samples.push({ t: e.t, cwnd, ssthresh, phase, sendBase, nextSeq, stats: { ...stats } });
  }

  const tEnd = events.length ? events[events.length - 1].t : 0;
  const maxCwnd = cwndSeries.reduce((m, p) => Math.max(m, p.value), 1);
  return { samples, cwndSeries, ssSeries, tEnd, maxCwnd };
}

/**
 * Find the connection state in force at a given moment.
 *
 * Returns the last sample at or before `t` — state persists until something
 * changes it, so the most recent past event is the answer. Called on every
 * animation frame by several components at once, hence the binary search rather
 * than a scan.
 *
 * @param {Sample[]} samples Samples from `buildTimeline`, in time order.
 * @param {number} t Virtual time to query, in milliseconds.
 * @returns {Sample|null} The state at that moment, or `null` for an empty trace.
 */
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

/**
 * Join a run and its continuation into one trace.
 *
 * Continuing a simulation returns only the new events, so they are appended to
 * what came before. The checkpoint and statistics come from the newer response:
 * the checkpoint must be the latest one for a further continuation to work, and
 * the statistics are already cumulative.
 *
 * @param {Object} a The earlier trace, with `events`, `checkpoint` and `stats`.
 * @param {Object} b The continuation, in the same shape.
 * @returns {Object} The combined trace.
 */
export function concatTraces(a, b) {
  return { events: a.events.concat(b.events), checkpoint: b.checkpoint, stats: b.stats };
}
