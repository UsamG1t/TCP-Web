<!-- @component
Instrument readout: the sender's state at the playhead.

Answers "what is the connection doing right now?" in numbers, while the diagrams
below answer it in pictures. Everything shown is the state at the current
playback position, so scrubbing backwards rewinds the counters too — they are
read from the precomputed timeline rather than accumulated as playback runs.

The phase is colour-coded to match the diagrams, so a glance is enough to tell
slow start from congestion avoidance from fast recovery.
-->
<script>
  import { player } from "../lib/player.js";
  import { stateAt } from "../lib/trace.js";

  $: s = $player;

  /** State sample in force at the playhead, or `null` before a run is loaded. */
  $: cur = s.timeline ? stateAt(s.timeline.samples, s.clock) : null;

  /** Colour per congestion-control phase, shared with the other views. */
  const phaseColor = {
    "slow-start": "var(--signal)",
    "congestion-avoidance": "var(--ok)",
    "fast-recovery": "var(--rtx)",
  };
  /**
   * Format a window value for display.
   *
   * Windows are fractional in congestion avoidance, so they are rounded to two
   * decimals; missing values render as a dash rather than as `null`.
   *
   * @param {number|null|undefined} v Value in segments.
   * @returns {string} Display string.
   */
  const fmt = (v) => (v == null ? "—" : (Math.round(v * 100) / 100).toString());
</script>

<div class="strip">
  <div class="cell">
    <span class="eyebrow">protocol</span>
    <span class="val">{s.config?.protocol ?? "—"}</span>
  </div>
  <div class="cell">
    <span class="eyebrow">phase</span>
    <span class="val" style="color:{phaseColor[cur?.phase] ?? 'var(--text)'}">{cur?.phase ?? "—"}</span>
  </div>
  <div class="cell">
    <span class="eyebrow">cwnd</span>
    <span class="val big">{fmt(cur?.cwnd)}</span>
  </div>
  <div class="cell">
    <span class="eyebrow">ssthresh</span>
    <span class="val">{fmt(cur?.ssthresh)}</span>
  </div>

  {#if cur}
    <div class="counters mono">
      <span>sent <b>{cur.stats.sent}</b></span>
      <span style="color:var(--ok)">ok <b>{cur.stats.delivered}</b></span>
      <span style="color:var(--loss)">lost <b>{cur.stats.lost}</b></span>
      <span style="color:var(--ack)">ack <b>{cur.stats.ackDelivered}</b></span>
      <span style="color:var(--rtx)">rtx <b>{cur.stats.retransmits}</b></span>
      <span style="color:var(--timeout)">rto <b>{cur.stats.timeouts}</b></span>
      <span>dup <b>{cur.stats.dupAcks}</b></span>
    </div>
  {/if}
</div>

<style>
  .strip {
    display: flex; align-items: center; gap: 26px; flex-wrap: wrap;
    padding: 14px 18px; border-bottom: 1px solid var(--line);
    background: var(--panel);
  }
  .cell { display: flex; flex-direction: column; gap: 3px; }
  .val { font-family: var(--font-mono); font-size: 15px; }
  .val.big { font-size: 22px; color: var(--text); }
  .counters { margin-left: auto; display: flex; gap: 16px; font-size: 12px; color: var(--muted); }
  .counters b { color: var(--text); font-weight: 600; }
</style>
