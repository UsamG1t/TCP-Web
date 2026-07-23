<!-- @component
Congestion window over time.

Plots `cwnd` as a solid line and `ssthresh` as a dashed one, on the same
horizontal scale as the ladder diagram directly above. That alignment is the
point of the whole layout: the sawtooth in this chart and the lost packet that
caused it sit in the same vertical column, which makes cause and effect legible
at a glance.

The shape of the curve is the protocol's signature — Tahoe's collapse to one
segment, Reno's halving, CUBIC's flattening approach to the previous maximum
followed by convex probing above it. A marker rides the curve at the playhead.
-->
<script>
  import { player } from "../lib/player.js";
  import { PAD_L, PAD_R, makeX, niceStep } from "../lib/layout.js";
  import { stateAt } from "../lib/trace.js";

  /** Measured component width in pixels, bound from the DOM. */
  let width = 800;

  /** Chart height in pixels. */
  const H = 172;

  /** Top padding, leaving room above the peak of the curve. */
  const padTop = 14;

  /** Bottom padding, reserved for the baseline. */
  const padBottom = 26;

  $: s = $player;
  $: x = makeX(width, s.tEnd);
  $: maxY = s.timeline ? Math.max(s.timeline.maxCwnd, 1) : 1;
  $: y = (v) => padTop + (1 - v / maxY) * (H - padTop - padBottom);

  $: grid = (() => {
    const step = niceStep(s.tEnd);
    const arr = [];
    for (let t = 0; t <= s.tEnd + 1; t += step) arr.push(t);
    return arr;
  })();

  /**
   * Convert a time series into an SVG path.
   *
   * Straight segments between samples, which is the honest representation: the
   * window really does change in steps, at the moment an acknowledgement or a
   * loss is processed, so smoothing would imply changes that never happened.
   *
   * The scales are parameters rather than closure references so that Svelte
   * tracks them as dependencies and the paths are rebuilt when the component is
   * resized or the trace grows.
   *
   * @param {Array<{t: number, value: number}>} series Points to plot.
   * @param {function(number): number} xScale Time-to-pixel mapping.
   * @param {function(number): number} yScale Value-to-pixel mapping.
   * @returns {string} An SVG path, or an empty string for an empty series.
   */
  function path(series, xScale, yScale) {
    if (!series || !series.length) return "";
    return series
      .map((p, i) => `${i ? "L" : "M"}${xScale(p.t).toFixed(1)} ${yScale(p.value).toFixed(1)}`)
      .join(" ");
  }
  $: cwndPath = s.timeline ? path(s.timeline.cwndSeries, x, y) : "";
  $: ssPath = s.timeline ? path(s.timeline.ssSeries, x, y) : "";
  $: cur = s.timeline ? stateAt(s.timeline.samples, s.clock) : null;
</script>

<div class="chart" bind:clientWidth={width}>
  <svg viewBox="0 0 {width} {H}" width="100%" height={H} role="img"
       aria-label="График окна перегрузки во времени">
    <!-- grid -->
    {#each grid as t}
      <line x1={x(t)} y1={padTop} x2={x(t)} y2={H - padBottom} stroke="var(--line-soft)" />
    {/each}
    <!-- y axis: 0 and max -->
    <line x1={PAD_L} y1={y(0)} x2={width - PAD_R} y2={y(0)} stroke="var(--line)" />
    <text x={PAD_L - 8} y={y(0) + 3} class="ylab" text-anchor="end">0</text>
    <text x={PAD_L - 8} y={y(maxY) + 3} class="ylab" text-anchor="end">{Math.round(maxY)}</text>

    {#if s.timeline}
      <path d={ssPath} fill="none" stroke="var(--muted)" stroke-width="1.2" stroke-dasharray="4 3" />
      <path d={cwndPath} fill="none" stroke="var(--ok)" stroke-width="1.8" />
      {#if cur && cur.cwnd != null}
        <circle cx={x(s.clock)} cy={y(cur.cwnd)} r="3.2" fill="var(--signal)" />
      {/if}
    {/if}

    <!-- playhead -->
    <line x1={x(s.clock)} y1={padTop} x2={x(s.clock)} y2={H - padBottom}
          stroke="var(--signal)" stroke-width="1.2" />
  </svg>
  <div class="legend mono">
    <span><i style="background:var(--ok)"></i>cwnd</span>
    <span><i style="background:var(--muted)"></i>ssthresh</span>
  </div>
</div>

<style>
  .chart { width: 100%; position: relative; }
  svg { display: block; }
  .ylab { fill: var(--muted); font-family: var(--font-mono); font-size: 10px; }
  .legend { position: absolute; top: 6px; right: 12px; display: flex; gap: 14px; font-size: 11px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 12px; height: 2px; display: inline-block; border-radius: 1px; }
</style>
