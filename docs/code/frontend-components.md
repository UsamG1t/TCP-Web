---
title: Frontend · components
parent: Code Reference
nav_order: 4
---

# Frontend · components

*Generated from source by `docs/_tools/gen_code_docs.py`. Edit the comments in the code, then re-run the generator.*

### `frontend/src/App.svelte`

Root component: layout, and the only place that talks to the API.

Owns the two things that cannot belong to any single view — the request
lifecycle and the error state — and leaves everything else to the player store,
which the child components read independently. That keeps the data flow
one-directional: requests come up as events, results go down into the store, and
the views follow the store.

The three diagrams are stacked in a deliberate order. The sliding-window strip
sits on top, in sequence-number space; below it the ladder and the window chart
share one horizontal time axis, so a lost packet and the dip it causes line up
vertically.

#### `let schema`

Parameter metadata from the API, fetched once at start-up.

#### `let busy`

Whether a simulation request is currently in flight.

#### `let error`

Message from the most recent failure, or `null`.

#### `async function handleRun(ev)`

Run a fresh simulation and hand the trace to the player.

Replaces whatever was loaded and rewinds the clock, so the new run plays
from the beginning.

**Parameters**

- `ev` (`CustomEvent`) — The `run` event from the configuration panel, carrying `config`, `duration` and `seed`.

#### `async function handleContinue(ev)`

Extend the current run and append the new events to the trace.

The checkpoint held in the store is sent back as the resume state, which is
what allows the server to continue without having kept anything itself. The
configuration comes from the form as it stands now, so the continuation can
differ from what came before it.

**Parameters**

- `ev` (`CustomEvent`) — The `continue` event from the configuration panel, carrying `config` and `duration`.

---

### `frontend/src/components/ConfigPanel.svelte`

Parameter form and the run controls.

Built entirely from the schema the backend publishes, rather than from a
hard-coded list of fields: adding a parameter on the server makes it appear here,
with the right default and the right bounds, without touching this file.

Two actions, and the difference between them matters. **Run** computes a fresh
trace from time zero. **Continue** extends the current one from where it ends,
carrying the checkpoint back to the server — and because the parameters are read
at that moment, changing the protocol or the loss rate first is what lets a run
switch behaviour partway through.

Both are emitted as events rather than handled here; the parent owns the requests.

**Events dispatched**

- `run` — detail `{ config, duration, seed }`
- `continue` — detail `{ config, duration }`

**Props:** `schema` (default `null`), `busy` (default `false`), `hasCheckpoint` (default `false`)

#### `export let schema`

Parameter metadata from `GET /schema`. The form stays hidden until it
arrives, since defaults and bounds both come from it.

**Type** — `Object|null`

#### `export let busy`

Whether a request is currently in flight. Disables both buttons so a run
cannot be started twice.

**Type** — `boolean`

#### `export let hasCheckpoint`

Whether a trace exists that could be continued. Controls whether the
continue button is available.

**Type** — `boolean`

#### `const LABELS`

Human-readable labels for the numeric parameters, keyed by schema name.

#### `let config`

Current form values, populated from the schema on arrival.

#### `let duration`

Seconds of virtual time to simulate, or to add when continuing.

#### `let seed`

Seed for reproducible loss decisions.

#### `const run`

Ask the parent to run a fresh simulation.

The configuration is copied rather than passed by reference, so that
editing the form afterwards cannot alter a request already under way.

#### `const cont`

Ask the parent to extend the current run.

No seed is sent: a continuation draws its randomness from the checkpoint,
which carries the generator state forward.

---

### `frontend/src/components/Ladder.svelte`

Time-sequence (ladder) diagram — the signature view.

Time runs left to right; the sender is the upper lane and the receiver the lower
one. Every packet is a diagonal line whose slope *is* the propagation delay, so
the geometry carries meaning: steeper links are faster, and the gap between a
segment's departure and its acknowledgement is the round-trip time drawn to
scale.

Colour encodes outcome — delivered, lost, retransmitted — and acknowledgements
return along fainter lines in the opposite direction. Lost packets stop at a
cross partway across instead of reaching the far lane.

Lines are drawn progressively: a packet is only extended as far as the playhead
has travelled, which is what makes packets appear to fly rather than simply
appear. The horizontal scale is shared with the window chart below, so a loss
here lines up vertically with the drop in the congestion window it causes.

#### `let width`

Measured component width in pixels, bound from the DOM.

#### `const H`

Diagram height in pixels.

#### `const senderY`

Vertical centre of the sender's lane.

#### `const receiverY`

Vertical centre of the receiver's lane.

#### `function dataSeg(f, clock, xScale)`

Compute the visible portion of a data packet's diagonal.

Interpolates between the two lanes by how far the packet has travelled at
the current instant, so a line grows as the playhead advances and is
complete once the packet has arrived.

The clock and the scale are taken as arguments rather than read from the
enclosing scope on purpose: Svelte derives the dependencies of a template
expression from what that expression mentions, so a value used only inside
a plain function would not be tracked, and the packets would sit frozen
while the playhead moved.

**Parameters**

- `f` (`Object`) — A flight from `buildFlights`.
- `clock` (`number`) — Current playback position, in virtual milliseconds.
- `xScale` (`function(number): number`) — Time-to-pixel mapping.

**Returns** (`{x0: number, y0: number, x1: number, y1: number, done: boolean}`) — Endpoints of the visible segment, and whether the journey has finished.

#### `function ackSeg(f, clock, xScale)`

Compute the visible portion of an acknowledgement's diagonal.

The mirror image of `dataSeg`: same interpolation, travelling from the
receiver's lane back up to the sender's.

**Parameters**

- `f` (`Object`) — An acknowledgement flight from `buildFlights`.
- `clock` (`number`) — Current playback position, in virtual milliseconds.
- `xScale` (`function(number): number`) — Time-to-pixel mapping.

**Returns** (`{x0: number, y0: number, x1: number, y1: number, done: boolean}`) — Endpoints of the visible segment, and whether it has arrived.

#### `const dataColor`

Pick the stroke colour for a data packet.

Retransmissions are called out before outcome, since "this is a repeat" is
the more informative fact when studying loss recovery.

**Parameters**

- `f` (`Object`) — A flight from `buildFlights`.

**Returns** (`string`) — A CSS custom property reference.

---

### `frontend/src/components/LogPanel.svelte`

Event log, synchronised with the playhead.

The diagrams show what happened; this shows it in words, and is where a
surprising moment gets pinned down — which duplicate acknowledgement was the
third, exactly which rule moved the window. Only events at or before the
playhead are listed, so the log rewinds along with everything else when
scrubbing.

Collapsed by default, since it is a detail view rather than something to watch
continuously. The listing is capped at the most recent entries: a long run
produces thousands of events, and rendering them all would cost more than it is
worth.

#### `let open`

Whether the panel is expanded.

#### `const COLOR`

Colour per event type, matching the palette used by the diagrams.

#### `function detail(e)`

Render the informative part of an event as a short string.

Events carry different payloads, so the field that matters is chosen by
what is present: a sequence number for packets, an acknowledgement number
(with a repeat count for duplicates) for ACKs, and the new value plus the
rule that produced it for window changes.

**Parameters**

- `e` (`Object`) — An event from the trace.

**Returns** (`string`) — Text for the log row, empty if nothing worth showing.

---

### `frontend/src/components/SlidingWindow.svelte`

The sliding window in sequence-number space.

Where the other two views plot time, this one plots sequence numbers: a strip of
cells, one per segment, with a bracket marking the window. As acknowledgements
arrive the bracket slides right — which is what the protocol family is named
after, and what neither of the time-based views actually shows.

Cells are colour-coded by state: acknowledged and behind the window, in flight,
usable but not yet sent, or outside the window entirely. Two carets mark the
pointers that define the window — `base`, the oldest unacknowledged segment, and
`next`, the one that will go out next. The bracket's width is the effective
window, so flow control is visible too: when the receiver's window is the
smaller of the two, the bracket stops growing even as `cwnd` climbs.

#### `let width`

Measured component width in pixels, bound from the DOM.

#### `const PAD`

Horizontal padding in pixels.

#### `const H`

Strip height in pixels.

#### `const bracketY`

Vertical position of the window bracket.

#### `const cellY`

Top edge of the cell row.

#### `const cellH`

Cell height in pixels.

#### `const caretY`

Vertical position of the `base` and `next` carets.

#### `function buildView(c, rw)`

Work out which cells to draw and what state each one is in.

Only a window's worth of sequence space is interesting, so the strip is
cropped to the neighbourhood of the pointers, with a couple of cells of
margin either side to make the sliding motion visible rather than abrupt.

A cell's state follows from where it falls relative to the two pointers and
the window edge: behind `base` it is acknowledged, between `base` and `next`
it is in flight, up to the window edge it is available to send, and beyond
that it is blocked until the window slides.

**Parameters**

- `c` (`Object`) — State sample at the playhead.
- `rw` (`number`) — The receiver's advertised window, in segments.

**Returns** (`Object`) — Cells to render, the first sequence number shown, the two pointers, the window's right edge and its effective size.

#### `const xOf`

Map a sequence number to a horizontal pixel position.

**Parameters**

- `seq` (`number`) — Sequence number.
- `first` (`number`) — First sequence number visible on the strip.
- `cw` (`number`) — Cell width in pixels.

**Returns** (`number`) — The x coordinate of that cell's left edge.

---

### `frontend/src/components/StateStrip.svelte`

Instrument readout: the sender's state at the playhead.

Answers "what is the connection doing right now?" in numbers, while the diagrams
below answer it in pictures. Everything shown is the state at the current
playback position, so scrubbing backwards rewinds the counters too — they are
read from the precomputed timeline rather than accumulated as playback runs.

The phase is colour-coded to match the diagrams, so a glance is enough to tell
slow start from congestion avoidance from fast recovery.

#### `const phaseColor`

Colour per congestion-control phase, shared with the other views.

#### `const fmt`

Format a window value for display.

Windows are fractional in congestion avoidance, so they are rounded to two
decimals; missing values render as a dash rather than as `null`.

**Parameters**

- `v` (`number|null|undefined`) — Value in segments.

**Returns** (`string`) — Display string.

---

### `frontend/src/components/Transport.svelte`

Transport controls: play, pause, restart, speed and scrubbing.

A media-player bar for the trace. Because the whole simulation is computed up
front, every control here is a cheap change to one number — the playback clock —
rather than anything that recomputes the run. Scrubbing is therefore instant and
works identically whether playback is running or paused.

All state lives in the player store; this component only issues commands.

#### `const speeds`

Selectable playback rates, as multiples of real time.

#### `const secs`

Format a virtual timestamp for the readout.

**Parameters**

- `ms` (`number`) — Virtual time in milliseconds.

**Returns** (`string`) — Seconds to one decimal place.

---

### `frontend/src/components/WindowChart.svelte`

Congestion window over time.

Plots `cwnd` as a solid line and `ssthresh` as a dashed one, on the same
horizontal scale as the ladder diagram directly above. That alignment is the
point of the whole layout: the sawtooth in this chart and the lost packet that
caused it sit in the same vertical column, which makes cause and effect legible
at a glance.

The shape of the curve is the protocol's signature — Tahoe's collapse to one
segment, Reno's halving, CUBIC's flattening approach to the previous maximum
followed by convex probing above it. A marker rides the curve at the playhead.

#### `let width`

Measured component width in pixels, bound from the DOM.

#### `const H`

Chart height in pixels.

#### `const padTop`

Top padding, leaving room above the peak of the curve.

#### `const padBottom`

Bottom padding, reserved for the baseline.

#### `function path(series, xScale, yScale)`

Convert a time series into an SVG path.

Straight segments between samples, which is the honest representation: the
window really does change in steps, at the moment an acknowledgement or a
loss is processed, so smoothing would imply changes that never happened.

The scales are parameters rather than closure references so that Svelte
tracks them as dependencies and the paths are rebuilt when the component is
resized or the trace grows.

**Parameters**

- `series` (`Array<{t: number, value: number}>`) — Points to plot.
- `xScale` (`function(number): number`) — Time-to-pixel mapping.
- `yScale` (`function(number): number`) — Value-to-pixel mapping.

**Returns** (`string`) — An SVG path, or an empty string for an empty series.
