<script>
  import { player } from "../lib/player.js";
  let open = false;

  $: s = $player;
  // events up to the playhead, most recent last; cap for performance
  $: visible = s.events.filter((e) => e.t <= s.clock).slice(-200);

  const COLOR = {
    packet_send: "var(--text)", fast_retransmit: "var(--rtx)",
    packet_deliver: "var(--ok)", packet_drop: "var(--loss)",
    ack_send: "var(--ack)", ack_deliver: "var(--ack)", ack_drop: "var(--loss)",
    dup_ack: "var(--muted)", timeout: "var(--timeout)",
    cwnd_change: "var(--signal)", ssthresh_change: "var(--muted)",
    phase_change: "var(--signal)",
  };

  function detail(e) {
    if (e.seq != null) return `seq ${e.seq}`;
    if (e.ack != null) return `ack ${e.ack}${e.count ? ` ×${e.count}` : ""}`;
    if (e.value != null) return `${e.value}${e.reason ? `  (${e.reason})` : ""}`;
    if (e.phase) return e.phase;
    return "";
  }
</script>

<section class="log" class:open>
  <button class="bar" on:click={() => (open = !open)}>
    <span class="eyebrow">event log</span>
    <span class="mono count">{visible.length}{s.events.length > 200 ? " (last 200)" : ""}</span>
    <span class="chev">{open ? "▾" : "▸"}</span>
  </button>
  {#if open}
    <div class="rows mono">
      {#each visible as e}
        <div class="row">
          <span class="t">{(e.t / 1000).toFixed(2)}s</span>
          <span class="ty" style="color:{COLOR[e.type] ?? 'var(--text)'}">{e.type}</span>
          <span class="d">{detail(e)}</span>
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  .log { border-top: 1px solid var(--line); background: var(--panel); }
  .bar {
    width: 100%; display: flex; align-items: center; gap: 12px;
    background: none; border: none; border-radius: 0; padding: 10px 18px;
  }
  .bar:hover { border: none; }
  .count { color: var(--muted); font-size: 11px; }
  .chev { margin-left: auto; color: var(--muted); }
  .rows { max-height: 190px; overflow-y: auto; padding: 0 18px 10px; }
  .row { display: grid; grid-template-columns: 66px 130px 1fr; gap: 10px; font-size: 12px; padding: 2px 0; }
  .t { color: var(--muted); }
  .d { color: var(--muted); }
</style>
