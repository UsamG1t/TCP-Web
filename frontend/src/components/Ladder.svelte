<script>
  import { player } from "../lib/player.js";
  import { PAD_L, PAD_R, makeX, niceStep } from "../lib/layout.js";

  let width = 800;
  const H = 250;
  const senderY = 40;
  const receiverY = H - 42;

  $: s = $player;
  $: clock = s.clock;
  $: x = makeX(width, s.tEnd);

  $: grid = (() => {
    const step = niceStep(s.tEnd);
    const arr = [];
    for (let t = 0; t <= s.tEnd + 1; t += step) arr.push(t);
    return arr;
  })();

  // clock and xScale are passed in explicitly so Svelte tracks them as
  // dependencies of the {@const} expressions (otherwise flights wouldn't
  // re-render as the clock advances).
  function dataSeg(f, clock, xScale) {
    const total = Math.max(f.tEnd - f.tSend, 1e-6);
    const visEnd = Math.min(f.tEnd, clock);
    const frac = Math.max(0, Math.min(1, (visEnd - f.tSend) / total));
    return {
      x0: xScale(f.tSend), y0: senderY,
      x1: xScale(visEnd), y1: senderY + frac * (receiverY - senderY),
      done: clock >= f.tEnd,
    };
  }
  function ackSeg(f, clock, xScale) {
    const total = Math.max(f.tEnd - f.tSend, 1e-6);
    const visEnd = Math.min(f.tEnd, clock);
    const frac = Math.max(0, Math.min(1, (visEnd - f.tSend) / total));
    return {
      x0: xScale(f.tSend), y0: receiverY,
      x1: xScale(visEnd), y1: receiverY + frac * (senderY - receiverY),
      done: clock >= f.tEnd,
    };
  }
  const dataColor = (f) =>
    f.retransmit ? "var(--rtx)" : f.delivered === false ? "var(--loss)" : "var(--ok)";
</script>

<div class="ladder" bind:clientWidth={width}>
  <svg viewBox="0 0 {width} {H}" width="100%" height={H} role="img"
       aria-label="Диаграмма время-последовательность передачи пакетов">
    <!-- grid -->
    {#each grid as t}
      <line x1={x(t)} y1="20" x2={x(t)} y2={H - 20} stroke="var(--line-soft)" />
      <text x={x(t)} y={H - 6} class="tick" text-anchor="middle">{(t / 1000).toFixed(1)}s</text>
    {/each}

    <!-- lanes -->
    <line x1={PAD_L} y1={senderY} x2={width - PAD_R} y2={senderY} stroke="var(--line)" />
    <line x1={PAD_L} y1={receiverY} x2={width - PAD_R} y2={receiverY} stroke="var(--line)" />
    <text x="10" y={senderY + 4} class="lane">SND</text>
    <text x="10" y={receiverY + 4} class="lane">RCV</text>

    <!-- ACK flights (drawn under data) -->
    {#each s.flights.ackFlights as f}
      {#if f.tSend <= clock}
        {@const g = ackSeg(f, clock, x)}
        <line x1={g.x0} y1={g.y0} x2={g.x1} y2={g.y1}
              stroke="var(--ack)" stroke-width="1"
              stroke-dasharray={f.delivered === false ? "3 3" : "0"}
              opacity={g.done ? 0.75 : 0.5} />
        {#if g.done && f.delivered === false}
          <g stroke="var(--loss)" stroke-width="1.3">
            <line x1={g.x1 - 3} y1={g.y1 - 3} x2={g.x1 + 3} y2={g.y1 + 3} />
            <line x1={g.x1 - 3} y1={g.y1 + 3} x2={g.x1 + 3} y2={g.y1 - 3} />
          </g>
        {/if}
      {/if}
    {/each}

    <!-- data flights -->
    {#each s.flights.dataFlights as f}
      {#if f.tSend <= clock}
        {@const g = dataSeg(f, clock, x)}
        <line x1={g.x0} y1={g.y0} x2={g.x1} y2={g.y1}
              stroke={dataColor(f)} stroke-width="1.6"
              opacity={g.done ? 1 : 0.85} />
        {#if g.done && f.delivered === false}
          <g stroke="var(--loss)" stroke-width="1.6">
            <line x1={g.x1 - 4} y1={g.y1 - 4} x2={g.x1 + 4} y2={g.y1 + 4} />
            <line x1={g.x1 - 4} y1={g.y1 + 4} x2={g.x1 + 4} y2={g.y1 - 4} />
          </g>
        {:else if g.done}
          <circle cx={g.x1} cy={g.y1} r="2.4" fill={dataColor(f)} />
        {/if}
      {/if}
    {/each}

    <!-- playhead -->
    <line x1={x(clock)} y1="16" x2={x(clock)} y2={H - 16}
          stroke="var(--signal)" stroke-width="1.2" />
  </svg>
</div>

<style>
  .ladder { width: 100%; }
  .tick { fill: var(--muted); font-family: var(--font-mono); font-size: 10px; }
  .lane { fill: var(--muted); font-family: var(--font-mono); font-size: 11px; letter-spacing: .05em; }
  svg { display: block; }
</style>
