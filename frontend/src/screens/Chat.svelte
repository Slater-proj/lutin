<script lang="ts">
  // The Chat screen: the conversations, the one that is open, the answer as it is written, and what Lutin asks before it acts.
  import { onMount } from "svelte";
  import Thread from "../components/Thread.svelte";
  import { api, ApiError, streamTurn } from "../lib/api";
  import { t } from "../lib/messages";
  import { applyEvent, newTurn, storedToItems, type LiveTurn } from "../lib/turn";
  import type { Conversation, ConversationSummary, Models, Status } from "../lib/types";

  let { status, onchanged }: { status: Status | null; onchanged: () => void } = $props();

  let conversations = $state<ConversationSummary[]>([]);
  let conversation = $state<Conversation | null>(null);
  let models = $state<Models | null>(null);
  let live = $state<LiveTurn | null>(null);
  let pending = $state("");
  let draft = $state("");
  let problem = $state("");
  let listOpen = $state(false);
  let scroller = $state<HTMLElement | null>(null);

  const items = $derived(storedToItems(conversation?.messages ?? []));
  const busy = $derived(live !== null);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function guarded(action: () => Promise<void>): Promise<void> {
    try {
      problem = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
  }

  async function loadList(): Promise<void> {
    conversations = (await api<{ conversations: ConversationSummary[] }>("GET", "/conversations")).conversations;
  }

  async function loadModels(): Promise<void> {
    models = await api<Models>("GET", "/models");
  }

  async function open(id: string): Promise<void> {
    await guarded(async () => {
      conversation = await api<Conversation>("GET", `/conversations/${encodeURIComponent(id)}`);
      listOpen = false;
    });
  }

  function startNew(): void {
    conversation = null;
    problem = "";
    listOpen = false;
  }

  async function remove(entry: ConversationSummary): Promise<void> {
    if (!confirm(t("chat.delete_confirm", entry.title || t("chat.untitled")))) return;
    await guarded(async () => {
      await api("DELETE", `/conversations/${encodeURIComponent(entry.id)}`);
      if (conversation?.id === entry.id) conversation = null;
      await loadList();
    });
  }

  async function send(): Promise<void> {
    const message = draft.trim();
    if (!message || busy) return;
    await guarded(async () => {
      if (conversation === null) {
        conversation = await api<Conversation>("POST", "/conversations", {});
      }
      const id = conversation.id;
      draft = "";
      pending = message;
      live = newTurn();
      try {
        await streamTurn(id, { message }, (event) => {
          if (live) live = applyEvent(live, event);
        });
      } catch (cause) {
        if (live !== null && live.blocks.length === 0) draft = message; // refused before anything was written: the message is given back
        throw cause;
      } finally {
        // What is stored is the truth: the conversation is read again, whether the stream ended well or was cut.
        const stored = await api<Conversation>("GET", `/conversations/${encodeURIComponent(id)}`).catch(() => null);
        if (stored) conversation = stored;
        pending = "";
        live = null;
        await loadList().catch(() => undefined);
        onchanged();
      }
    });
  }

  async function stop(): Promise<void> {
    const id = conversation?.id;
    if (id) await guarded(async () => void (await api("POST", `/conversations/${encodeURIComponent(id)}/stop`, {})));
  }

  async function answerApproval(approved: boolean): Promise<void> {
    const approval = live?.approval;
    if (!approval) return;
    await guarded(async () => {
      await api("POST", `/approvals/${encodeURIComponent(approval.id)}`, { approved });
      if (live) live = { ...live, approval: null };
    });
  }

  async function answerMemory(choice: "summary" | "file"): Promise<void> {
    const id = conversation?.id;
    if (!id) return;
    await guarded(async () => {
      await api("POST", `/conversations/${encodeURIComponent(id)}/memory-choice`, { choice });
      if (live) live = { ...live, memoryChoice: false };
    });
  }

  async function chooseModel(event: Event): Promise<void> {
    const model = (event.currentTarget as HTMLSelectElement).value;
    await guarded(async () => {
      await api("PATCH", "/settings", { model });
      await loadModels();
      onchanged();
    });
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  function onSubmit(event: SubmitEvent): void {
    event.preventDefault();
    void send();
  }

  $effect(() => {
    // Follow the answer while it is written: each change of the conversation or of the live turn scrolls to the end.
    void items;
    void live;
    void pending;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });

  onMount(() => {
    void guarded(async () => {
      await Promise.all([loadList(), loadModels()]);
    });
  });
</script>

<div class="chat" class:list-open={listOpen}>
  <aside class="list" aria-label={t("chat.conversations")}>
    <div class="list-head">
      <button type="button" class="button primary" onclick={startNew}>{t("chat.new")}</button>
      <button type="button" class="button quiet close" onclick={() => (listOpen = false)}>{t("chat.hide_list")}</button>
    </div>
    {#if conversations.length === 0}
      <p class="empty">{t("chat.empty_list")}</p>
    {:else}
      <ul>
        {#each conversations as entry (entry.id)}
          <li>
            <button type="button" class="entry" aria-current={conversation?.id === entry.id ? "true" : undefined} onclick={() => open(entry.id)}>
              <span class="title">{entry.title || t("chat.untitled")}</span>
              {#if entry.pinned}<span class="tag">{t("chat.pinned")}</span>{/if}
            </button>
            <button type="button" class="button quiet remove" onclick={() => remove(entry)} disabled={busy && conversation?.id === entry.id}>
              <span aria-hidden="true">×</span><span class="visually-hidden">{t("chat.delete")} : {entry.title || t("chat.untitled")}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  <section class="main">
    <header>
      <button type="button" class="button quiet open-list" onclick={() => (listOpen = true)}>{t("chat.show_list")}</button>
      <h1>{conversation?.title || t("chat.untitled")}</h1>
      <label class="model">
        <span>{t("chat.model")}</span>
        <select onchange={chooseModel} disabled={busy || !models || models.models.length === 0}>
          {#if !models || models.models.length === 0}
            <option>{t("chat.no_model")}</option>
          {:else}
            {#if !models.models.some((model) => model.name === models?.current)}<option value={models.current} selected>{models.current}</option>{/if}
            {#each models.models as model (model.name)}
              <option value={model.name} selected={model.name === models.current}>{model.name}</option>
            {/each}
          {/if}
        </select>
      </label>
    </header>

    <div class="scroll" bind:this={scroller}>
      {#if status && !status.engine.running}<p class="banner">{t("chat.engine_stopped", status.engine.name)}</p>{/if}
      {#if items.length === 0 && !pending && !live}
        <div class="welcome">
          <p class="hello">{t("chat.welcome")}</p>
          <p>{t("chat.welcome_hint")}</p>
        </div>
      {:else}
        <Thread {items} {pending} {live} />
      {/if}
    </div>

    <div class="dock">
      {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
      {#if live?.autoApprovalSuspended}<p class="hint">{t("approval.suspended", live.autoApprovalSuspended)}</p>{/if}
      {#if live?.approval}
        <div class="card" role="group" aria-label={t("approval.heading")}>
          <p class="card-head">{t("approval.heading")}</p>
          <p class="card-title">{live.approval.title}</p>
          {#if live.approval.detail}<p class="pre">{live.approval.detail}</p>{/if}
          {#if live.approval.diff}<pre>{live.approval.diff}</pre>{/if}
          {#if live.approval.reason}<p class="hint">{live.approval.reason}</p>{/if}
          <div class="actions">
            <button type="button" class="button primary" onclick={() => answerApproval(true)}>{t("approval.approve")}</button>
            <button type="button" class="button danger" onclick={() => answerApproval(false)}>{t("approval.refuse")}</button>
          </div>
        </div>
      {/if}
      {#if live?.memoryChoice}
        <div class="card" role="group" aria-label={t("memory.heading")}>
          <p class="card-head">{t("memory.heading")}</p>
          <p>{t("memory.body")}</p>
          <div class="actions">
            <button type="button" class="button" onclick={() => answerMemory("summary")}>{t("memory.summary")}</button>
            <button type="button" class="button" onclick={() => answerMemory("file")}>{t("memory.file")}</button>
          </div>
        </div>
      {/if}
      <form class="composer" onsubmit={onSubmit}>
        <label class="visually-hidden" for="message">{t("chat.message")}</label>
        <textarea id="message" rows="2" placeholder={t("chat.placeholder")} aria-describedby="keys" bind:value={draft} onkeydown={onKey}></textarea>
        {#if busy}
          <button type="button" class="button danger" onclick={stop}>{t("chat.stop")}</button>
        {:else}
          <button type="submit" class="button primary" disabled={!draft.trim()}>{t("chat.send")}</button>
        {/if}
      </form>
      <p class="meter" id="keys">
        {#if live?.tokens}{t("chat.tokens", live.tokens.used, live.tokens.total)}{live.tokensPerSecond ? " · " + t("chat.speed", live.tokensPerSecond) : ""}{:else}{t("chat.keys")}{/if}
      </p>
    </div>
  </section>
</div>

<style>
  .chat {
    display: grid;
    grid-template-columns: var(--list-width) minmax(0, 1fr);
    flex: 1;
    min-height: 0;
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-height: 0;
    padding: var(--space-3);
    overflow-y: auto;
    border-right: 1px solid var(--color-border);
  }

  .list-head {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .close,
  .open-list {
    display: none;
  }

  .list ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .list li {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }

  .entry {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    text-align: left;
    cursor: pointer;
  }

  .entry:hover {
    background: var(--color-surface-raised);
  }

  .entry[aria-current="true"] {
    background: var(--color-accent-soft);
    font-weight: 600;
  }

  .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tag {
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }

  .remove {
    min-width: var(--target);
    padding: 0;
    color: var(--color-text-muted);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }

  header {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }

  h1 {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: var(--text-md);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .model {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--color-text-muted);
  }

  select {
    min-height: var(--target);
    max-width: 14rem;
    padding: 0 var(--space-2);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    color: var(--color-text);
  }

  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  .welcome {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-width: var(--measure);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
    color: var(--color-text-muted);
  }

  .hello {
    font-size: var(--text-lg);
    font-weight: 600;
    color: var(--color-text);
  }

  .banner,
  .hint {
    margin: var(--space-3) auto 0;
    max-width: var(--measure);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
  }

  .dock {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    width: 100%;
    max-width: var(--measure);
    max-height: 65%;
    margin: 0 auto;
    padding: var(--space-2) var(--space-4) var(--space-3);
    overflow-y: auto;
  }

  .hint {
    margin: 0;
    max-width: none;
  }

  .problem {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border: 2px solid var(--color-accent);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    box-shadow: var(--shadow-raised);
  }

  .card-head {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--color-text-muted);
  }

  .card-title {
    font-weight: 600;
  }

  .pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .card pre {
    max-height: 14rem;
    margin: 0;
    padding: var(--space-2) var(--space-3);
    overflow: auto;
    border-radius: var(--radius-sm);
    background: var(--color-code-bg);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .composer {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
  }

  textarea {
    flex: 1;
    min-width: 0;
    min-height: var(--target);
    max-height: 12rem;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    resize: vertical;
  }

  .meter {
    min-height: 1.4em;
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }

  /* Narrow screens: the list of conversations covers the screen when asked, and is hidden otherwise. */
  @media (max-width: 900px) {
    .chat {
      grid-template-columns: minmax(0, 1fr);
    }

    .list {
      display: none;
      border-right: 0;
    }

    .chat.list-open .list {
      display: flex;
    }

    .chat.list-open .main {
      display: none;
    }

    .close,
    .open-list {
      display: inline-flex;
      align-items: center;
    }

    .model span {
      display: none;
    }

    select {
      max-width: 9rem;
    }
  }
</style>
