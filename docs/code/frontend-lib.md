---
title: Frontend · lib
parent: Code Reference
nav_order: 3
---

# Frontend · lib

*Generated from source by `docs/_tools/gen_code_docs.py`. Edit the comments in the code, then re-run the generator.*

### `frontend/src/lib/api.js`

Client for the simulator's REST API.

Three calls, all thin: fetch the parameter schema, run a simulation, continue
one. Everything else the UI does happens locally on the returned trace.

The base URL is configurable because the frontend runs in two quite different
places. In development Vite serves it on port 5173 while the API is on 5000,
so requests are cross-origin and need an absolute URL. In production both are
behind the same nginx, so `VITE_API_BASE` is set to `/api` at build time and
requests become same-origin.

Network failures are translated into a message worth showing a user, because
the overwhelmingly likely cause in development is simply that the backend is
not running — a bare `TypeError: Failed to fetch` would not say so.

#### `async function post(path, body)`

POST a JSON body to the API and return the parsed response.

**Parameters**

- `path` (`string`) — Path appended to the configured base URL.
- `body` (`Object`) — Request body, serialised as JSON.

**Returns** (`Promise<Object>`) — The parsed response body.

**Throws** (`Error`) — If the backend is unreachable, or replies with an error status. The API's own `error` message is preferred when present, since it explains which parameter was rejected and why.

#### `export async function getSchema()`

Fetch the parameter schema used to build the configuration form.

Requested once at start-up. Taking defaults and bounds from the server keeps
the form in step with what the backend will actually accept, instead of
duplicating the limits in the UI.

**Returns** (`Promise<Object>`) — Numeric parameters with their defaults and ranges, the available protocols and retransmission modes, and the duration limits.

**Throws** (`Error`) — If the backend is unreachable or replies with an error status.

#### `export function runSimulation({ config, duration, seed })`

Run a new simulation from time zero.

**Parameters**

- `params` (`Object`) — Request parameters.
  - `params.config` (`Object`) — Simulation parameters from the form.
  - `params.duration` (`number`) — Seconds of virtual time to simulate.
  - `params.seed` (`number`) — Seed for reproducible loss decisions.

**Returns** (`Promise<Object>`) — The trace (`events`), a `checkpoint` for continuing, and summary `stats`.

#### `export function continueSimulation({ config, duration, resumeState })`

Extend an existing run, optionally under different parameters.

The checkpoint carries everything needed to resume, so the server keeps no
state between the two calls. Passing a modified `config` is what lets the user
change protocol or loss rate partway through and watch the sender react;
segments already in flight keep the fate they were given.

**Parameters**

- `params` (`Object`) — Request parameters.
  - `params.config` (`Object`) — Parameters for the continuation.
  - `params.duration` (`number`) — Additional seconds of virtual time.
  - `params.resumeState` (`Object`) — The `checkpoint` from the previous response.

**Returns** (`Promise<Object>`) — Only the new events, plus an updated checkpoint and cumulative stats. The caller appends them to the existing trace.

---

### `frontend/src/lib/layout.js`

Shared horizontal layout for the time-based views.

The ladder diagram and the window chart are separate components stacked one
above the other, and the whole point of that arrangement is that a loss on the
ladder lines up vertically with the dip it causes in the congestion window.
That only holds if both map time to pixels identically, so the mapping lives
here rather than in either component.

#### `export const PAD_L`

Left padding in pixels, reserved for the lane and axis labels.

**Type** — `number`

#### `export const PAD_R`

Right padding in pixels, so the final events do not touch the edge.

**Type** — `number`

#### `export function makeX(width, tEnd)`

Build a function mapping virtual time to a horizontal pixel position.

The whole trace is fitted to the available width, so the scale changes as the
trace grows or the window is resized. Both the lower bounds guard against
division by zero on an empty trace or a component that has not been measured
yet — either would otherwise produce `NaN` coordinates and an invisible SVG.

**Parameters**

- `width` (`number`) — Full component width in pixels, padding included.
- `tEnd` (`number`) — Virtual time at the end of the trace, in milliseconds.

**Returns** (`function(number): number`) — Converts a timestamp to an x coordinate.

#### `export function niceStep(tEnd)`

Choose a round interval between grid lines.

Aims for roughly ten divisions, then rounds up to the next 1, 2 or 5 times a
power of ten — the intervals people read comfortably. Without the rounding a
grid line would land on values like 1237 ms and the axis would be unreadable.

**Parameters**

- `tEnd` (`number`) — Virtual time at the end of the trace, in milliseconds.

**Returns** (`number`) — Interval between grid lines, in milliseconds.

---

### `frontend/src/lib/player.js`

Playback store: the virtual clock every view reads from.

The trace is computed in one shot by the backend and then *played*, so
something has to own the notion of "now". That is this store. It holds the
trace and a virtual clock, and while playing it advances that clock by the
elapsed wall-clock time multiplied by the speed setting.

Components never animate anything themselves; they subscribe, read the clock,
and draw whatever is true at that instant. Because the whole trace is known in
advance, seeking is as cheap as playing — moving the clock backwards is no
different from moving it forwards.

The derived views (`flights`, `timeline`) are recomputed only when the trace
changes, never per frame.

#### `function createPlayer()`

Create the playback store.

Called once; the module exports the single instance. The animation frame
handle and the timestamp of the previous frame are kept in the closure rather
than in the store, since they are machinery rather than state anyone should
render.

**Returns** (`Object`) — A Svelte store with `subscribe` plus the transport methods.

#### `function _cancel()`

Cancel any pending animation frame.

#### `function tick(now)`

Advance the virtual clock by one animation frame.

The step is the real time elapsed since the previous frame times the speed
setting, so playback runs at a constant rate whatever the frame rate. On
reaching the end of the trace the clock stops exactly there rather than
overshooting, and playback stops.

**Parameters**

- `now` (`number`) — Timestamp supplied by `requestAnimationFrame`.

#### `load(result, config)`

Load a freshly computed trace, replacing whatever was loaded before.

Derives the flights and the state timeline once, here, so that playback
only ever looks values up. The clock returns to zero and playback starts
paused, leaving the user to press play.

**Parameters**

- `result` (`Object`) — The response from `POST /simulate`.
- `config` (`Object`) — The configuration that produced it. Kept because the timeline needs the retransmission mode, and the readouts display the protocol.

#### `append(result, config)`

Append a continuation to the trace already loaded.

The clock is deliberately left alone: the timeline grows to the right and
playback carries on, so extending a run feels continuous rather than like
starting again.

The derived views are rebuilt from the combined event list rather than
patched, because a continuation can affect what came before it — a segment
still in flight at the boundary only finds its outcome in the new events.

**Parameters**

- `result` (`Object`) — The response from the continuation request.
- `config` (`Object`) — The configuration the continuation ran under, which may differ from the original.

#### `play()`

Start or resume playback.

Playing from the very end rewinds to the start first, so the play button
always does something visible instead of appearing dead once a run has
finished.

#### `pause()`

Pause playback, leaving the clock where it is.

#### `reset()`

Stop playback and return the clock to the beginning of the trace.

#### `seek(t)`

Jump the clock to a given moment, clamped to the trace.

Used by the scrub control. Playback state is untouched, so scrubbing works
both while paused and while playing.

**Parameters**

- `t` (`number`) — Target virtual time, in milliseconds.

#### `setSpeed(v)`

Set the playback rate.

Takes effect on the next frame; no need to restart playback.

**Parameters**

- `v` (`number`) — Multiplier applied to real elapsed time.

#### `export const player`

The application's single playback store.

Components subscribe with `$player` and call the transport methods directly.

**Type** — `Object`

---

### `frontend/src/lib/trace.js`

Trace processing: turning the backend's event list into what the UI draws.

The API returns a flat, chronological list of events. That is the right shape
to transmit but the wrong shape to render, because every view needs something
different: the ladder diagram needs each packet's departure *and* arrival
paired into a single line to draw, while the readouts need the cumulative
state at whatever instant the playhead sits on.

This module derives both, in one pass each, so playback itself stays cheap —
during animation nothing here runs again; the player only looks things up.

Deliberately free of Svelte and of the DOM, so it can be unit-tested on its
own against a trace captured from the backend.

#### type `DataFlight`

One data segment's journey from sender to receiver.

**Properties**

- `seq` (`number`) — Sequence number carried by the segment.
- `tSend` (`number`) — Virtual time it left the sender, in milliseconds.
- `tEnd` (`number`) — Virtual time it arrived or was lost.
- `delivered` (`boolean|null`) — `true` if it arrived, `false` if it was lost.
- `retransmit` (`boolean`) — Whether this was a repeat transmission.
- `fast` (`boolean`) — Whether it was a fast retransmit, triggered by duplicate acknowledgements rather than by the timer.

#### type `AckFlight`

One acknowledgement's journey back from receiver to sender.

**Properties**

- `ack` (`number`) — The cumulative acknowledgement number.
- `tSend` (`number`) — Virtual time the receiver sent it.
- `tEnd` (`number`) — Virtual time it arrived or was lost.
- `delivered` (`boolean`) — Whether it reached the sender.

#### type `Sample`

The complete connection state immediately after one event.

**Properties**

- `t` (`number`) — Virtual time of the event, in milliseconds.
- `cwnd` (`number|null`) — Congestion window in segments.
- `ssthresh` (`number|null`) — Slow-start threshold in segments.
- `phase` (`string`) — One of `slow-start`, `congestion-avoidance`, `fast-recovery`.
- `sendBase` (`number`) — Oldest unacknowledged sequence number.
- `nextSeq` (`number`) — Next sequence number the sender will use.
- `stats` (`Object`) — Cumulative counters up to this point.

#### `export function buildFlights(events)`

Pair send events with their outcomes, producing one record per journey.

The ladder diagram draws a line per packet, which needs both endpoints — but
the trace reports departure and arrival as separate events, possibly far
apart. This walks the trace once, holding each departure until its outcome
appears.

Sequence numbers repeat when a segment is retransmitted, so pending
departures are held in per-sequence FIFO queues: the first outcome for a given
number belongs to the first transmission still waiting for one.

Anything still airborne when the trace ends is given a zero-length flight, so
a partial trace never yields a line with no end.

**Parameters**

- `events` (`Array<Object>`) — The trace as returned by `POST /simulate`.

**Returns** (`{dataFlights: DataFlight[], ackFlights: AckFlight[]}`) — Journeys in both directions, in departure order.

#### `const EMPTY_STATS`

Build a fresh set of cumulative counters, all at zero.

#### `export function buildTimeline(events, mode = "gobackn")`

Replay the trace once, recording the full connection state after every event.

Scrubbing has to answer "what did things look like at time t?" instantly and
for arbitrary t, so rather than recomputing on demand the answer is
precomputed for every event and then found by binary search (see `stateAt`).
One sample per event keeps the array aligned with the trace and makes lookups
exact rather than interpolated.

The window pointers are reconstructed rather than read: the backend does not
put `sendBase` and `nextSeq` in the trace, but they follow from it — an
arriving acknowledgement is by definition the new `sendBase`, and the highest
sequence number sent so far gives `nextSeq`. The one subtlety is a timeout
under go-back-n, which rewinds the sender, so `nextSeq` must be pulled back to
`sendBase` to match. That is why the retransmission mode has to be passed in.

**Parameters**

- `events` (`Array<Object>`) — The trace as returned by `POST /simulate`.
- `mode` (`string`) *optional*, default `"gobackn"` — Retransmission mode, `gobackn` or `selective`.

**Returns** (`{samples: Sample[], cwndSeries: Array<Object>, ssSeries: Array<Object>, tEnd: number, maxCwnd: number}`) — Per event samples, the two series plotted by the window chart, the end of the trace, and the peak window used to scale that chart's axis.

#### `export function stateAt(samples, t)`

Find the connection state in force at a given moment.

Returns the last sample at or before `t` — state persists until something
changes it, so the most recent past event is the answer. Called on every
animation frame by several components at once, hence the binary search rather
than a scan.

**Parameters**

- `samples` (`Sample[]`) — Samples from `buildTimeline`, in time order.
- `t` (`number`) — Virtual time to query, in milliseconds.

**Returns** (`Sample|null`) — The state at that moment, or `null` for an empty trace.

#### `export function concatTraces(a, b)`

Join a run and its continuation into one trace.

Continuing a simulation returns only the new events, so they are appended to
what came before. The checkpoint and statistics come from the newer response:
the checkpoint must be the latest one for a further continuation to work, and
the statistics are already cumulative.

**Parameters**

- `a` (`Object`) — The earlier trace, with `events`, `checkpoint` and `stats`.
- `b` (`Object`) — The continuation, in the same shape.

**Returns** (`Object`) — The combined trace.

---

### `frontend/src/main.js`

Application entry point.

Loads the global stylesheet — which defines the design tokens every component
refers to — and mounts the root component into the placeholder in
`index.html`. Nothing else happens here; the app takes over from `App.svelte`.
