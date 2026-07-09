<script>
  import { player } from "../lib/player.js";
  import { stateAt } from "../lib/trace.js";

  $: s = $player;
  $: cur = s.timeline ? stateAt(s.timeline.samples, s.clock) : null;

  const phaseColor = {
    "slow-start": "var(--signal)",
    "congestion-avoidance": "var(--ok)",
    "fast-recovery": "var(--rtx)",
  };
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
