<!-- @component
Transport controls: play, pause, restart, speed and scrubbing.

A media-player bar for the trace. Because the whole simulation is computed up
front, every control here is a cheap change to one number — the playback clock —
rather than anything that recomputes the run. Scrubbing is therefore instant and
works identically whether playback is running or paused.

All state lives in the player store; this component only issues commands.
-->
<script>
  import { player } from "../lib/player.js";

  /** Selectable playback rates, as multiples of real time. */
  const speeds = [0.5, 1, 2, 4];

  $: s = $player;

  /**
   * Format a virtual timestamp for the readout.
   *
   * @param {number} ms Virtual time in milliseconds.
   * @returns {string} Seconds to one decimal place.
   */
  const secs = (ms) => (ms / 1000).toFixed(1);
</script>

<div class="transport">
  <button class="play" on:click={() => (s.playing ? player.pause() : player.play())}
          disabled={!s.loaded} aria-label={s.playing ? "Пауза" : "Воспроизвести"}>
    {s.playing ? "❚❚" : "▶"}
  </button>
  <button on:click={() => player.reset()} disabled={!s.loaded} aria-label="В начало">↺</button>

  <div class="speeds">
    {#each speeds as v}
      <button class:active={s.speed === v} on:click={() => player.setSpeed(v)}>{v}×</button>
    {/each}
  </div>

  <input class="scrub" type="range" min="0" max={s.tEnd || 1} step="1"
         value={s.clock} disabled={!s.loaded}
         on:input={(e) => player.seek(+e.target.value)}
         aria-label="Позиция во времени" />

  <div class="time mono">{secs(s.clock)}s / {secs(s.tEnd)}s</div>
</div>

<style>
  .transport {
    display: flex; align-items: center; gap: 14px;
    padding: 12px 18px; border-top: 1px solid var(--line); background: var(--panel);
  }
  .play { width: 44px; font-size: 13px; }
  .speeds { display: flex; gap: 4px; }
  .speeds button { padding: 5px 9px; font-family: var(--font-mono); font-size: 12px; }
  .speeds button.active { border-color: var(--signal); color: var(--signal); }
  .scrub { flex: 1; }
  .time { color: var(--muted); font-size: 12px; min-width: 96px; text-align: right; }
</style>
