// Playback store. Holds the trace + a virtual clock that advances at
// speed × wall-clock while playing. Components read $player and derive what to
// draw at the current clock.

import { writable, get } from "svelte/store";
import { buildFlights, buildTimeline } from "./trace.js";

function createPlayer() {
  const store = writable({
    config: null,
    events: [],
    flights: { dataFlights: [], ackFlights: [] },
    timeline: null,
    checkpoint: null,
    stats: null,
    clock: 0,
    tEnd: 0,
    playing: false,
    speed: 1,
    loaded: false,
  });

  let raf = null;
  let last = 0;

  function _cancel() {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
  }

  function tick(now) {
    const s = get(store);
    if (!s.playing) { raf = null; return; }
    const dt = (now - last) * s.speed;
    last = now;
    let clock = s.clock + dt;
    if (clock >= s.tEnd) {
      store.update((x) => ({ ...x, clock: x.tEnd, playing: false }));
      raf = null;
      return;
    }
    store.update((x) => ({ ...x, clock }));
    raf = requestAnimationFrame(tick);
  }

  return {
    subscribe: store.subscribe,

    // load a fresh trace (resets the clock)
    load(result, config) {
      _cancel();
      const flights = buildFlights(result.events);
      const timeline = buildTimeline(result.events, config?.retransmitMode);
      store.update((s) => ({
        ...s,
        config,
        events: result.events,
        flights,
        timeline,
        checkpoint: result.checkpoint,
        stats: result.stats,
        clock: 0,
        tEnd: timeline.tEnd,
        playing: false,
        loaded: true,
      }));
    },

    // append a continuation (keeps the clock where it is)
    append(result, config) {
      store.update((s) => {
        const events = s.events.concat(result.events);
        const flights = buildFlights(events);
        const timeline = buildTimeline(events, config?.retransmitMode);
        return {
          ...s,
          config,
          events,
          flights,
          timeline,
          checkpoint: result.checkpoint,
          stats: result.stats,
          tEnd: timeline.tEnd,
        };
      });
    },

    play() {
      const s = get(store);
      if (!s.loaded || s.playing) return;
      store.update((x) => ({
        ...x,
        clock: x.clock >= x.tEnd ? 0 : x.clock,
        playing: true,
      }));
      last = performance.now();
      _cancel();
      raf = requestAnimationFrame(tick);
    },

    pause() {
      store.update((x) => ({ ...x, playing: false }));
      _cancel();
    },

    reset() {
      store.update((x) => ({ ...x, playing: false, clock: 0 }));
      _cancel();
    },

    seek(t) {
      store.update((x) => ({ ...x, clock: Math.max(0, Math.min(t, x.tEnd)) }));
    },

    setSpeed(v) {
      store.update((x) => ({ ...x, speed: v }));
    },
  };
}

export const player = createPlayer();
