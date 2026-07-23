<!-- @component
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
-->
<script>
  import { createEventDispatcher } from "svelte";

  /**
   * Parameter metadata from `GET /schema`. The form stays hidden until it
   * arrives, since defaults and bounds both come from it.
   * @type {Object|null}
   */
  export let schema = null;

  /**
   * Whether a request is currently in flight. Disables both buttons so a run
   * cannot be started twice.
   * @type {boolean}
   */
  export let busy = false;

  /**
   * Whether a trace exists that could be continued. Controls whether the
   * continue button is available.
   * @type {boolean}
   */
  export let hasCheckpoint = false;

  const dispatch = createEventDispatcher();

  /** Human-readable labels for the numeric parameters, keyed by schema name. */
  const LABELS = {
    packetTime: "Задержка данных (мс)",
    ackTime: "Задержка ACK (мс)",
    sendWindow: "Начальное окно",
    recvWindow: "Окно приёма",
    packetLoss: "Потери данных (%)",
    ackLoss: "Потери ACK (%)",
    timeout: "Стартовый RTO (мс)",
    bandwidth: "Пропускная (сег/с)",
  };

  /** Current form values, populated from the schema on arrival. */
  let config = null;

  /** Seconds of virtual time to simulate, or to add when continuing. */
  let duration = 30;

  /** Seed for reproducible loss decisions. */
  let seed = 1;

  // Populate the form from the schema, once. The guard on `config` keeps later
  // schema updates from discarding what the user has typed.
  $: if (schema && !config) {
    const c = {};
    for (const [k, v] of Object.entries(schema.numeric)) c[k] = v.default;
    c.protocol = schema.protocols.includes("reno") ? "reno" : schema.protocols[0];
    c.retransmitMode = schema.retransmitModes[0];
    config = c;
    duration = schema.duration.default;
  }

  /**
   * Ask the parent to run a fresh simulation.
   *
   * The configuration is copied rather than passed by reference, so that
   * editing the form afterwards cannot alter a request already under way.
   */
  const run = () => dispatch("run", { config: { ...config }, duration, seed });

  /**
   * Ask the parent to extend the current run.
   *
   * No seed is sent: a continuation draws its randomness from the checkpoint,
   * which carries the generator state forward.
   */
  const cont = () => dispatch("continue", { config: { ...config }, duration });
</script>

<aside class="panel">
  <div class="head">
    <span class="eyebrow">parameters</span>
  </div>

  {#if config}
    <div class="group">
      <label>
        <span>Протокол</span>
        <select bind:value={config.protocol}>
          {#each schema.protocols as p}<option value={p}>{p}</option>{/each}
        </select>
      </label>
      <label>
        <span>Ретрансмиссия</span>
        <select bind:value={config.retransmitMode}>
          {#each schema.retransmitModes as m}<option value={m}>{m}</option>{/each}
        </select>
      </label>
    </div>

    <div class="group grid">
      {#each Object.entries(schema.numeric) as [k, meta]}
        <label>
          <span>{LABELS[k] ?? k}</span>
          <input type="number" min={meta.min} max={meta.max}
                 bind:value={config[k]} />
        </label>
      {/each}
    </div>

    <div class="group grid">
      <label>
        <span>Длительность (с)</span>
        <input type="number" min={schema.duration.min} max={schema.duration.max}
               bind:value={duration} />
      </label>
      <label>
        <span>Seed</span>
        <input type="number" step="1" bind:value={seed} />
      </label>
    </div>

    <div class="actions">
      <button class="primary" on:click={run} disabled={busy}>
        {busy ? "Считаю…" : "Запустить"}
      </button>
      <button on:click={cont} disabled={busy || !hasCheckpoint}
              title="Досчитать ещё N секунд от текущего конца — можно с новыми параметрами">
        Продолжить +{duration}с
      </button>
    </div>
    <p class="hint">«Продолжить» досчитывает трассу дальше от её конца; параметры можно
      предварительно изменить.</p>
  {:else}
    <p class="hint">Загрузка параметров…</p>
  {/if}
</aside>

<style>
  .panel {
    background: var(--panel); border-right: 1px solid var(--line);
    padding: 16px; width: 280px; min-width: 280px; overflow-y: auto;
  }
  .head { margin-bottom: 14px; }
  .group { margin-bottom: 16px; display: flex; flex-direction: column; gap: 10px; }
  .group.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  label { display: flex; flex-direction: column; gap: 4px; }
  label span { font-size: 11px; color: var(--muted); }
  .actions { display: flex; gap: 8px; margin-top: 6px; }
  .primary { flex: 1; border-color: var(--signal); color: var(--signal); }
  .primary:hover:not(:disabled) { background: rgba(70, 199, 242, 0.12); }
  .hint { font-size: 11px; color: var(--muted); line-height: 1.5; margin: 10px 0 0; }
</style>
