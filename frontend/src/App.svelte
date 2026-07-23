<!-- @component
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
-->
<script>
  import { onMount } from "svelte";
  import { getSchema, runSimulation, continueSimulation } from "./lib/api.js";
  import { player } from "./lib/player.js";

  import ConfigPanel from "./components/ConfigPanel.svelte";
  import StateStrip from "./components/StateStrip.svelte";
  import SlidingWindow from "./components/SlidingWindow.svelte";
  import Ladder from "./components/Ladder.svelte";
  import WindowChart from "./components/WindowChart.svelte";
  import Transport from "./components/Transport.svelte";
  import LogPanel from "./components/LogPanel.svelte";

  /** Parameter metadata from the API, fetched once at start-up. */
  let schema = null;

  /** Whether a simulation request is currently in flight. */
  let busy = false;

  /** Message from the most recent failure, or `null`. */
  let error = null;

  /** Whether a run exists that could be continued. */
  $: hasCheckpoint = $player.checkpoint != null;

  // Fetch the schema before anything else: the form cannot render without it.
  onMount(async () => {
    try {
      schema = await getSchema();
    } catch (e) {
      error = e.message;
    }
  });

  /**
   * Run a fresh simulation and hand the trace to the player.
   *
   * Replaces whatever was loaded and rewinds the clock, so the new run plays
   * from the beginning.
   *
   * @param {CustomEvent} ev The `run` event from the configuration panel,
   *   carrying `config`, `duration` and `seed`.
   */
  async function handleRun(ev) {
    const { config, duration, seed } = ev.detail;
    busy = true; error = null;
    try {
      const result = await runSimulation({ config, duration, seed });
      player.load(result, config);
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  /**
   * Extend the current run and append the new events to the trace.
   *
   * The checkpoint held in the store is sent back as the resume state, which is
   * what allows the server to continue without having kept anything itself. The
   * configuration comes from the form as it stands now, so the continuation can
   * differ from what came before it.
   *
   * @param {CustomEvent} ev The `continue` event from the configuration panel,
   *   carrying `config` and `duration`.
   */
  async function handleContinue(ev) {
    const { config, duration } = ev.detail;
    busy = true; error = null;
    try {
      const result = await continueSimulation({
        config, duration, resumeState: $player.checkpoint,
      });
      player.append(result, config);
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="app">
  <header>
    <div class="brand">
      <span class="dot"></span>
      <h1>TCP Congestion Scope</h1>
    </div>
    <span class="eyebrow">sliding-window · classic · tahoe · reno · cubic</span>
  </header>

  <div class="body">
    <ConfigPanel {schema} {busy} {hasCheckpoint}
                 on:run={handleRun} on:continue={handleContinue} />

    <main>
      <StateStrip />

      <div class="stage">
        {#if $player.loaded}
          <div class="scope-label eyebrow">sliding window</div>
          <SlidingWindow />
          <div class="scope-label eyebrow">time–sequence</div>
          <Ladder />
          <div class="scope-label eyebrow">congestion window</div>
          <WindowChart />
        {:else}
          <div class="empty">
            {#if error}
              <p class="err">{error}</p>
            {:else}
              <p>Задай параметры слева и нажми «Запустить», чтобы посчитать прогон.</p>
            {/if}
          </div>
        {/if}
      </div>

      <Transport />
      <LogPanel />
    </main>
  </div>

  {#if error && $player.loaded}
    <div class="toast err">{error}</div>
  {/if}
</div>

<style>
  .app { display: flex; flex-direction: column; height: 100vh; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 18px; border-bottom: 1px solid var(--line); background: var(--panel);
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand h1 { font-size: 15px; letter-spacing: .01em; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--signal);
         box-shadow: 0 0 10px var(--signal); }
  .body { flex: 1; display: flex; min-height: 0; }
  main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .stage { flex: 1; overflow: auto; padding: 8px 0; }
  .scope-label { padding: 8px 18px 2px; }
  .empty { height: 100%; display: flex; align-items: center; justify-content: center;
           color: var(--muted); padding: 40px; text-align: center; }
  .err { color: var(--loss); }
  .toast { position: fixed; bottom: 16px; right: 16px; background: var(--panel-2);
           border: 1px solid var(--loss); border-radius: var(--r); padding: 10px 14px; }
</style>
