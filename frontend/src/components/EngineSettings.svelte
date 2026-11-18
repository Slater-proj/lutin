<script lang="ts">
  // The settings of one engine (docs/modernization/PARITY.md, item 11), inside its card on the Engines tab: an address, a key (never shown again) and a
  // variant for an engine reached by address; llama.cpp's router, models kept, experts on the processor and pinned version; its install and models
  // folders; the OpenAI-compatible server chosen and its ports. Only what this engine has is shown; a box left empty goes back to the default.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Folder = { current: string; proposed: string | null; default: string; custom: boolean; changeable: boolean; models: { current: string; changeable: boolean } | null } | null;
  type View = {
    engine: string;
    address_changeable: boolean;
    url: string;
    key_set: boolean;
    variant: string;
    folder: Folder;
    server: string | null;
    advanced: { router: boolean; router_possible: boolean; models_kept: number; cpu_moe_layers: number; cpu_moe_possible: boolean; pinned_version: string } | null;
    colibri?: { port: number; installed: boolean; model: string; model_ok: boolean };
    lmstudio?: { port: number; installed: boolean };
    exllamav3?: { port: number; installed: boolean };
  };

  let { engine, canConfigure }: { engine: string; canConfigure: boolean } = $props();

  const VARIANTS = ["auto", "cuda", "vulkan", "cpu", "metal"];
  let view = $state<View | null>(null);
  let form = $state<Record<string, string | number | boolean>>({});
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  function shown(answer: View): void {
    view = answer;
    form = {
      url: answer.url,
      key: "",
      variant: answer.variant,
      install_folder: answer.folder?.custom ? answer.folder.current : "",
      models_folder: "",
      ...(answer.advanced ? { router: answer.advanced.router, models_kept: answer.advanced.models_kept, cpu_moe_layers: answer.advanced.cpu_moe_layers, pinned_version: answer.advanced.pinned_version } : {}),
      ...(answer.colibri ? { colibri_model: answer.colibri.model, colibri_port: answer.colibri.port } : {}),
      ...(answer.lmstudio ? { lmstudio_port: answer.lmstudio.port } : {}),
      ...(answer.exllamav3 ? { exllamav3_port: answer.exllamav3.port } : {}),
    };
  }

  async function save(fields: string[]): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
    try {
      const body = Object.fromEntries(fields.filter((name) => !(name === "key" && form.key === "")).map((name) => [name, form[name]]));
      shown(await api<View>("PATCH", `/engines/${encodeURIComponent(engine)}/settings`, body));
      notice = t("web.saved");
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => {
    api<View>("GET", `/engines/${encodeURIComponent(engine)}/settings`).then(shown, (cause) => (problem = explain(cause)));
  });
</script>

<div class="engine-settings">
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if view}
    {#if !canConfigure}<p class="muted">{t("engines.not_here")}</p>{/if}
    <fieldset disabled={!canConfigure || busy}>
      {#if view.address_changeable}
        <label>{t("eset.url")}<input type="url" placeholder="http://127.0.0.1:8080" bind:value={form.url} /></label>
        <label>{t("eset.key")}<input type="password" autocomplete="off" placeholder={view.key_set ? t("eset.key_set") : ""} bind:value={form.key} /></label>
        {#if engine === "llamacpp"}
          <label>{t("eset.variant")}<select bind:value={form.variant}>{#each VARIANTS as variant (variant)}<option value={variant}>{variant}</option>{/each}</select></label>
        {/if}
        <p class="help">{t("eset.url_help")}</p>
        <div class="actions"><button type="button" class="button" onclick={() => save(engine === "llamacpp" ? ["url", "key", "variant"] : ["url", "key"])}>{t("web.save")}</button></div>
      {/if}

      {#if view.advanced}
        <h4>{t("eset.advanced")}</h4>
        <label class="check"><input type="checkbox" bind:checked={form.router as boolean} disabled={!view.advanced.router_possible} /> {t("eset.router")}</label>
        <p class="help">{view.advanced.router_possible ? t("eset.router_help") : t("eset.router_impossible")}</p>
        <label>{t("eset.models_kept")}<input type="number" min="1" max="8" bind:value={form.models_kept} /></label>
        {#if view.advanced.cpu_moe_possible}<label>{t("eset.cpu_moe")}<input type="number" min="0" max="512" bind:value={form.cpu_moe_layers} /></label><p class="help">{t("eset.cpu_moe_help")}</p>{/if}
        <label>{t("eset.pinned")}<input type="text" placeholder="b6500" bind:value={form.pinned_version} /></label>
        <p class="help">{t("eset.pinned_help")}</p>
        <div class="actions"><button type="button" class="button" onclick={() => save(["router", "models_kept", "pinned_version", ...(view?.advanced?.cpu_moe_possible ? ["cpu_moe_layers"] : [])])}>{t("web.save")}</button></div>
      {/if}

      {#if view.folder}
        <h4>{t("eset.folders")}</h4>
        <p class="muted">{t("eset.install_folder_now", view.folder.current)}</p>
        {#if view.folder.changeable}
          <label>{t("eset.install_folder")}<input type="text" placeholder={view.folder.proposed ?? view.folder.default} bind:value={form.install_folder} /></label>
          <div class="actions"><button type="button" class="button" onclick={() => save(["install_folder"])}>{t("web.save")}</button></div>
        {/if}
        {#if view.folder.models}
          <p class="muted">{t("eset.models_folder_now", view.folder.models.current)}</p>
          {#if view.folder.models.changeable}
            <label>{t("eset.models_folder")}<input type="text" bind:value={form.models_folder} /></label>
            <p class="help">{t("eset.models_folder_help")}</p>
            <div class="actions"><button type="button" class="button" onclick={() => save(["models_folder"])}>{t("web.save")}</button></div>
          {/if}
        {/if}
      {/if}

      {#if view.colibri}
        <h4>Colibri</h4>
        <label>{t("eset.colibri_model")}<input type="text" bind:value={form.colibri_model} /></label>
        <label>{t("eset.port")}<input type="number" min="1024" max="65535" bind:value={form.colibri_port} /></label>
        <div class="actions"><button type="button" class="button" onclick={() => save(["colibri_model", "colibri_port"])}>{t("web.save")}</button></div>
      {/if}
      {#if view.lmstudio}
        <h4>LM Studio</h4>
        <label>{t("eset.port")}<input type="number" min="1024" max="65535" bind:value={form.lmstudio_port} /></label>
        <div class="actions"><button type="button" class="button" onclick={() => save(["lmstudio_port"])}>{t("web.save")}</button></div>
      {/if}
      {#if view.exllamav3}
        <h4>ExLlamaV3</h4>
        <label>{t("eset.port")}<input type="number" min="1024" max="65535" bind:value={form.exllamav3_port} /></label>
        <div class="actions"><button type="button" class="button" onclick={() => save(["exllamav3_port"])}>{t("web.save")}</button></div>
      {/if}
    </fieldset>
  {/if}
</div>

<style>
  .engine-settings,
  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  fieldset {
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
  }

  p,
  h4 {
    margin: 0;
  }

  h4 {
    margin-top: var(--space-2);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 32rem;
  }

  label.check {
    flex-direction: row;
    align-items: center;
    gap: var(--space-2);
  }

  .muted,
  .help {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    max-width: var(--measure);
    overflow-wrap: anywhere;
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .problem {
    color: var(--color-danger);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
