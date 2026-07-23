/**
 * Playback store: the virtual clock every view reads from.
 *
 * The trace is computed in one shot by the backend and then *played*, so
 * something has to own the notion of "now". That is this store. It holds the
 * trace and a virtual clock, and while playing it advances that clock by the
 * elapsed wall-clock time multiplied by the speed setting.
 *
 * Components never animate anything themselves; they subscribe, read the clock,
 * and draw whatever is true at that instant. Because the whole trace is known in
 * advance, seeking is as cheap as playing — moving the clock backwards is no
 * different from moving it forwards.
 *
 * The derived views (`flights`, `timeline`) are recomputed only when the trace
 * changes, never per frame.
 */

import { writable, get } from "svelte/store";
import { buildFlights, buildTimeline } from "./trace.js";

/**
 * Create the playback store.
 *
 * Called once; the module exports the single instance. The animation frame
 * handle and the timestamp of the previous frame are kept in the closure rather
 * than in the store, since they are machinery rather than state anyone should
 * render.
 *
 * @returns {Object} A Svelte store with `subscribe` plus the transport methods.
 */
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

  /** Cancel any pending animation frame. */
  function _cancel() {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
  }

  /**
   * Advance the virtual clock by one animation frame.
   *
   * The step is the real time elapsed since the previous frame times the speed
   * setting, so playback runs at a constant rate whatever the frame rate. On
   * reaching the end of the trace the clock stops exactly there rather than
   * overshooting, and playback stops.
   *
   * @param {number} now Timestamp supplied by `requestAnimationFrame`.
   */
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

    /**
     * Load a freshly computed trace, replacing whatever was loaded before.
     *
     * Derives the flights and the state timeline once, here, so that playback
     * only ever looks values up. The clock returns to zero and playback starts
     * paused, leaving the user to press play.
     *
     * @param {Object} result The response from `POST /simulate`.
     * @param {Object} config The configuration that produced it. Kept because
     *   the timeline needs the retransmission mode, and the readouts display
     *   the protocol.
     */
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

    /**
     * Append a continuation to the trace already loaded.
     *
     * The clock is deliberately left alone: the timeline grows to the right and
     * playback carries on, so extending a run feels continuous rather than like
     * starting again.
     *
     * The derived views are rebuilt from the combined event list rather than
     * patched, because a continuation can affect what came before it — a segment
     * still in flight at the boundary only finds its outcome in the new events.
     *
     * @param {Object} result The response from the continuation request.
     * @param {Object} config The configuration the continuation ran under, which
     *   may differ from the original.
     */
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

    /**
     * Start or resume playback.
     *
     * Playing from the very end rewinds to the start first, so the play button
     * always does something visible instead of appearing dead once a run has
     * finished.
     */
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

    /** Pause playback, leaving the clock where it is. */
    pause() {
      store.update((x) => ({ ...x, playing: false }));
      _cancel();
    },

    /** Stop playback and return the clock to the beginning of the trace. */
    reset() {
      store.update((x) => ({ ...x, playing: false, clock: 0 }));
      _cancel();
    },

    /**
     * Jump the clock to a given moment, clamped to the trace.
     *
     * Used by the scrub control. Playback state is untouched, so scrubbing works
     * both while paused and while playing.
     *
     * @param {number} t Target virtual time, in milliseconds.
     */
    seek(t) {
      store.update((x) => ({ ...x, clock: Math.max(0, Math.min(t, x.tEnd)) }));
    },

    /**
     * Set the playback rate.
     *
     * Takes effect on the next frame; no need to restart playback.
     *
     * @param {number} v Multiplier applied to real elapsed time.
     */
    setSpeed(v) {
      store.update((x) => ({ ...x, speed: v }));
    },
  };
}

/**
 * The application's single playback store.
 *
 * Components subscribe with `$player` and call the transport methods directly.
 * @type {Object}
 */
export const player = createPlayer();
