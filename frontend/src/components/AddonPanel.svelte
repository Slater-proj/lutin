<script lang="ts">
  // The live panel of a running add-on: the pairing code and the paired phones of Telegram, the replies drafted for you to read before they leave (Telegram, mail, X), and the posts of X.
  // Nothing leaves without a click here: a draft is sent with the text as it is in its box, or thrown away. For the machine itself only (the pairing code is the key to the add-on).
  import { onDestroy, onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  let { id }: { id: string } = $props();

  type Draft = { id: string; from: string; text: string; at: number; request?: string; subject?: string; address?: string; excerpt?: string; name?: string };
  type Post = { id: string; text: string; state: "draft" | "scheduled" | "published"; at: number; scheduled_for: number; detail: string };
  type Panel = {
    listening: boolean;
    error: string;
    pairing_code?: string;
    devices?: { id: string; name: string }[];
    drafts?: Draft[];
    address?: string;
    handle?: string;
    published_today?: number;
    daily_limit?: number;
    posts?: Post[];
    replies?: Draft[];
  };

  let panel = $state<Panel | null | undefined>(undefined);
  let problem = $state("");
  let busy = $state(false);
  let forgetting = $state("");
  let edits = $state<Record<string, string>>({});
  let moments = $state<Record<string, string>>({});
  let brief = $state("");
  let count = $state(1);
  let timer: ReturnType<typeof setInterval> | undefined;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("panel.only_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const path = (suffix: string): string => `/addons/${encodeURIComponent(id)}/${suffix}`;

  const load = (): Promise<void> =>
    act(async () => {
      panel = (await api<{ panel: Panel | null }>("GET", path("panel"))).panel;
    });

  async function follow(): Promise<void> {
    if (busy || !panel) return;
    try {
      panel = (await api<{ panel: Panel | null }>("GET", path("panel"))).panel;
    } catch {
      /* the next turn of the timer asks again */
    }
  }

  const run = (action: string, body: Record<string, unknown> = {}): Promise<void> =>
    act(async () => {
      panel = (await api<{ panel: Panel | null }>("POST", path("panel/" + action), body)).panel;
      forgetting = "";
    });

  const textOf = (item: { id: string; text: string }): string => edits[item.id] ?? item.text;
  const stamp = (seconds: number): string => (seconds ? new Date(seconds * 1000).toLocaleString() : "");

  const write = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return run("write_posts", { brief: brief.trim(), count }).then(() => {
      if (!problem) brief = "";
    });
  };

  const schedule = (post: Post): Promise<void> => run("schedule_post", { post: post.id, text: textOf(post), at: new Date(moments[post.id]).getTime() / 1000 });

  onMount(() => {
    void load();
    timer = setInterval(() => void follow(), 5000);
  });
  onDestroy(() => clearInterval(timer));
</script>

{#snippet drafts(items: Draft[], send: string, discard: string)}
  <ul class="drafts">
    {#each items as draft (draft.id)}
      <li class="draft">
        <p><strong>{draft.from}</strong>{#if draft.subject} · {draft.subject}{/if} <span class="muted">{stamp(draft.at)}</span></p>
        {#if draft.request || draft.excerpt}<p class="quote">{draft.request ?? draft.excerpt}</p>{/if}
        <label for={"draft-" + id + "-" + draft.id}>{t("panel.reply")}</label>
        <textarea id={"draft-" + id + "-" + draft.id} rows="3" value={textOf(draft)} oninput={(event) => (edits[draft.id] = event.currentTarget.value)}></textarea>
        <div class="actions">
          <button type="button" class="button primary" disabled={busy || !textOf(draft).trim()} onclick={() => run(send, { draft: draft.id, text: textOf(draft) })}>{t("panel.send")}</button>
          <button type="button" class="button" disabled={busy} onclick={() => run(discard, { draft: draft.id })}>{t("panel.discard")}</button>
        </div>
      </li>
    {/each}
  </ul>
{/snippet}

{#if panel}
  <div class="panel" role="group" aria-label={t("panel.title")}>
    <h4>{t("panel.title")}</h4>
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class={panel.error ? "warn" : "muted"}>{panel.error ? t("panel.error", panel.error) : panel.listening ? t("panel.listening") : t("panel.not_listening")}</p>

    {#if panel.pairing_code !== undefined}
      <div class="pairing">
        <p>{t("panel.code_help")}</p>
        <p class="code" aria-label={t("panel.code")}>{panel.pairing_code || "—"}</p>
        <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => run("new_pairing_code")}>{t("panel.new_code")}</button></div>
      </div>
      <h5>{t("panel.devices")}</h5>
      {#if panel.devices?.length}
        <ul class="devices">
          {#each panel.devices as device (device.id)}
            <li>
              <span>{device.name || device.id}</span>
              {#if forgetting === device.id}
                <span class="confirm" role="group" aria-label={t("panel.forget_confirm", device.name || device.id)}>
                  <span>{t("panel.forget_confirm", device.name || device.id)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => run("forget_device", { device: device.id })}>{t("panel.forget_yes")}</button>
                  <button type="button" class="button" onclick={() => (forgetting = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (forgetting = device.id)}>{t("panel.forget")}</button>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">{t("panel.no_devices")}</p>
      {/if}
    {/if}

    {#if panel.handle !== undefined}
      <p class="muted">{t("panel.handle", panel.handle || "?", panel.published_today ?? 0, panel.daily_limit ?? 0)}</p>
      <form class="write" onsubmit={write}>
        <label for={"write-" + id}>{t("panel.write")}</label>
        <textarea id={"write-" + id} rows="2" bind:value={brief} autocomplete="off"></textarea>
        <label for={"count-" + id}>{t("panel.count")}</label>
        <select id={"count-" + id} bind:value={count}>
          {#each [1, 2, 3, 4, 5] as number (number)}<option value={number}>{number}</option>{/each}
        </select>
        <div class="actions"><button type="submit" class="button" disabled={busy || !brief.trim()}>{t("panel.write_go")}</button></div>
      </form>
      <h5>{t("panel.posts")}</h5>
      {#if panel.posts?.length}
        <ul class="drafts">
          {#each panel.posts as post (post.id)}
            <li class="draft">
              <p>
                <span class="badge">{t(("panel.post." + post.state) as "panel.post.draft")}</span>
                {#if post.state === "scheduled"}<span class="muted">{stamp(post.scheduled_for)}</span>{/if}
                {#if post.state === "published"}<span class="muted">{stamp(post.at)}</span>{/if}
              </p>
              {#if post.state === "published"}
                <p class="quote">{post.text}</p>
              {:else}
                <label for={"post-" + id + "-" + post.id}>{t("panel.post_text")}</label>
                <textarea id={"post-" + id + "-" + post.id} rows="3" value={textOf(post)} oninput={(event) => (edits[post.id] = event.currentTarget.value)}></textarea>
                <label for={"when-" + id + "-" + post.id}>{t("panel.when")}</label>
                <input id={"when-" + id + "-" + post.id} type="datetime-local" bind:value={moments[post.id]} />
                <div class="actions">
                  <button type="button" class="button primary" disabled={busy || !textOf(post).trim()} onclick={() => run("publish_post", { post: post.id, text: textOf(post) })}>{t("panel.publish")}</button>
                  <button type="button" class="button" disabled={busy || !moments[post.id]} onclick={() => schedule(post)}>{t("panel.schedule")}</button>
                  <button type="button" class="button" disabled={busy} onclick={() => run("edit_post", { post: post.id, text: textOf(post) })}>{t("panel.save")}</button>
                  <button type="button" class="button" disabled={busy} onclick={() => run("delete_post", { post: post.id })}>{t("panel.delete")}</button>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">{t("panel.no_posts")}</p>
      {/if}
    {/if}

    {#if panel.drafts || panel.replies}
      <h5>{t("panel.drafts")}</h5>
      {#if (panel.drafts ?? panel.replies ?? []).length}
        {@render drafts(panel.drafts ?? panel.replies ?? [], panel.replies ? "send_reply" : "send_draft", panel.replies ? "discard_reply" : "discard_draft")}
      {:else}
        <p class="muted">{t("panel.no_drafts")}</p>
      {/if}
    {/if}
  </div>
{:else if panel === undefined && problem}
  <p class="problem" role="alert">{problem}</p>
{/if}

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }

  h4,
  h5,
  p {
    margin: 0;
  }

  h4 {
    font-size: var(--text-md);
  }

  h5 {
    font-size: var(--text-sm);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .code {
    font-size: var(--text-lg);
    font-weight: 700;
    letter-spacing: 0.2em;
  }

  .drafts,
  .devices {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .devices li,
  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .draft,
  .write,
  .pairing {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .draft {
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }

  .quote {
    padding-left: var(--space-3);
    border-left: 3px solid var(--color-border-strong);
    color: var(--color-text-muted);
    overflow-wrap: anywhere;
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  label {
    font-weight: 600;
  }

  textarea,
  select,
  input[type="datetime-local"] {
    max-width: 32rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .problem,
  .warn {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
