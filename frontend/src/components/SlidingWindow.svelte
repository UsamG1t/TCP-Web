<!-- @component
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
-->
<script>
  import { player } from "../lib/player.js";
  import { stateAt } from "../lib/trace.js";

  /** Measured component width in pixels, bound from the DOM. */
  let width = 800;

  /** Horizontal padding in pixels. */
  const PAD = 12;

  /** Strip height in pixels. */
  const H = 104;

  /** Vertical position of the window bracket. */
  const bracketY = 20;

  /** Top edge of the cell row. */
  const cellY = 34;

  /** Cell height in pixels. */
  const cellH = 30;

  /** Vertical position of the `base` and `next` carets. */
  const caretY = cellY + cellH + 6;

  $: s = $player;
  $: recvWindow = s.config?.recvWindow ?? 64;
  $: cur = s.timeline ? stateAt(s.timeline.samples, s.clock) : null;
  $: view = cur ? buildView(cur, recvWindow) : null;
  $: nCells = view ? view.cells.length : 1;
  $: cellW = Math.max(18, Math.min(46, (width - PAD * 2) / nCells));

  // Geometry is computed here rather than in the markup because Svelte only
  // permits {@const} as a direct child of a block, not of an element.
  $: bx0 = view ? xOf(view.sendBase, view.first, cellW) : 0;
  $: bx1 = view ? xOf(view.windowEnd, view.first, cellW) : 0;
  $: baseX = view ? xOf(view.sendBase, view.first, cellW) + cellW / 2 : 0;
  $: nextX = view ? xOf(view.nextSeq, view.first, cellW) + cellW / 2 : 0;

  /**
   * Work out which cells to draw and what state each one is in.
   *
   * Only a window's worth of sequence space is interesting, so the strip is
   * cropped to the neighbourhood of the pointers, with a couple of cells of
   * margin either side to make the sliding motion visible rather than abrupt.
   *
   * A cell's state follows from where it falls relative to the two pointers and
   * the window edge: behind `base` it is acknowledged, between `base` and `next`
   * it is in flight, up to the window edge it is available to send, and beyond
   * that it is blocked until the window slides.
   *
   * @param {Object} c State sample at the playhead.
   * @param {number} rw The receiver's advertised window, in segments.
   * @returns {Object} Cells to render, the first sequence number shown, the two
   *   pointers, the window's right edge and its effective size.
   */
  function buildView(c, rw) {
    const sendBase = c.sendBase ?? 0;
    const nextSeq = c.nextSeq ?? 0;
    const winSize = Math.min(c.cwnd ?? 0, rw);
    const windowEnd = sendBase + winSize;
    const first = Math.max(0, sendBase - 2);
    const last = Math.max(nextSeq, Math.ceil(windowEnd)) + 2;
    const cells = [];
    for (let seq = first; seq <= last; seq++) {
      let state;
      if (seq < sendBase) state = "acked";
      else if (seq < nextSeq) state = "inflight";
      else if (seq < windowEnd) state = "usable";
      else state = "outside";
      cells.push({ seq, state });
    }
    return { cells, first, sendBase, nextSeq, windowEnd, winSize };
  }

  /**
   * Map a sequence number to a horizontal pixel position.
   *
   * @param {number} seq Sequence number.
   * @param {number} first First sequence number visible on the strip.
   * @param {number} cw Cell width in pixels.
   * @returns {number} The x coordinate of that cell's left edge.
   */
  const xOf = (seq, first, cw) => PAD + (seq - first) * cw;

  const FILL = { acked: "var(--ok)", inflight: "var(--signal)", usable: "none", outside: "none" };
  const STROKE = { acked: "var(--ok)", inflight: "var(--signal)", usable: "var(--muted)", outside: "var(--line)" };
  const TEXT = { acked: "var(--ok)", inflight: "var(--signal)", usable: "var(--muted)", outside: "var(--line)" };
</script>

<div class="win" bind:clientWidth={width}>
  {#if view}
    <svg viewBox="0 0 {width} {H}" width="100%" height={H} role="img"
         aria-label="Скользящее окно в пространстве номеров сегментов">
      <!-- window bracket -->
      <path d="M{bx0} {bracketY + 6} L{bx0} {bracketY} L{bx1} {bracketY} L{bx1} {bracketY + 6}"
            fill="none" stroke="var(--rtx)" stroke-width="1.3" />
      <text x={(bx0 + bx1) / 2} y={bracketY - 4} class="wlabel" text-anchor="middle">
        окно {view.winSize.toFixed(1)}
      </text>

      <!-- cells -->
      {#each view.cells as c, i}
        <rect x={PAD + i * cellW + 1} y={cellY} width={cellW - 2} height={cellH} rx="3"
              fill={FILL[c.state]} fill-opacity={c.state === "acked" || c.state === "inflight" ? 0.2 : 0}
              stroke={STROKE[c.state]} stroke-width="1"
              stroke-dasharray={c.state === "usable" ? "3 3" : "0"} />
        <text x={PAD + i * cellW + cellW / 2} y={cellY + cellH / 2 + 4}
              class="seq" text-anchor="middle" fill={TEXT[c.state]}>{c.seq}</text>
      {/each}

      <!-- pointers -->
      <g class="ptr">
        <path d="M{baseX} {caretY} l-4 6 l8 0 z" fill="var(--ok)" />
        <text x={baseX} y={caretY + 20} text-anchor="middle" fill="var(--ok)">base</text>
      </g>
      <g class="ptr">
        <path d="M{nextX} {caretY} l-4 6 l8 0 z" fill="var(--signal)" />
        <text x={nextX} y={caretY + 20} text-anchor="middle" fill="var(--signal)">next</text>
      </g>
    </svg>

    <div class="legend mono">
      <span><i style="background:var(--ok)"></i>подтверждён</span>
      <span><i style="background:var(--signal)"></i>в полёте</span>
      <span><i class="hollow" style="border-color:var(--muted)"></i>доступен</span>
    </div>
  {/if}
</div>

<style>
  .win { width: 100%; position: relative; overflow-x: auto; }
  svg { display: block; }
  .wlabel { fill: var(--rtx); font-family: var(--font-mono); font-size: 11px; }
  .seq { font-family: var(--font-mono); font-size: 11px; }
  .ptr text { font-family: var(--font-mono); font-size: 10px; }
  .legend { position: absolute; top: 2px; right: 12px; display: flex; gap: 14px; font-size: 11px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 12px; height: 8px; border-radius: 2px; display: inline-block; opacity: .5; }
  .legend i.hollow { background: none !important; border: 1px dashed; opacity: 1; }
</style>
