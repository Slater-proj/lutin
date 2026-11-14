<script lang="ts">
  // The Chat screen: the conversations, the one that is open, the answer as it is written, and what Lutin asks before it acts.
  import { onMount } from "svelte";
  import Icon from "../components/Icon.svelte";
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
  let box = $state<HTMLTextAreaElement | null>(null);

  const SUGGESTIONS = ["chat.suggest_explain", "chat.suggest_write", "chat.suggest_fix", "chat.suggest_summarise"] as const;

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

  function suggest(text: string): void {
    draft = text;
    box?.focus();
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
      <button type="button" class="new" onclick={startNew}><Icon name="plus" size={18} /><span>{t("chat.new")}</span></button>
      <button type="button" class="icon close" onclick={() => (listOpen = false)}><Icon name="close" /><span class="visually-hidden">{t("chat.hide_list")}</span></button>
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
            <button type="button" class="icon remove" onclick={() => remove(entry)} disabled={busy && conversation?.id === entry.id}>
              <Icon name="trash" size={16} /><span class="visually-hidden">{t("chat.delete")} : {entry.title || t("chat.untitled")}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  <section class="main">
    <header>
      <button type="button" class="icon open-list" onclick={() => (listOpen = true)}><Icon name="menu" /><span class="visually-hidden">{t("chat.show_list")}</span></button>
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
          <img src="/logo.svg" alt="" width="64" height="64" />
          <h2>{t("chat.welcome")}</h2>
          <p>{t("chat.welcome_hint")}</p>
          <ul class="suggestions" aria-label={t("chat.suggestions")}>
            {#each SUGGESTIONS as key (key)}
              <li><button type="button" class="chip" onclick={() => suggest(t(key))}>{t(key)}</button></li>
            {/each}
          </ul>
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
        <textarea id="message" rows="1" placeholder={t("chat.placeholder")} aria-describedby="keys" bind:value={draft} bind:this={box} onkeydown={onKey}></textarea>
        {#if busy}
          <button type="button" class="round stop" onclick={stop}><Icon name="stop" /><span class="visually-hidden">{t("chat.stop")}</span></button>
        {:else}
          <button type="submit" class="round send" disabled={!draft.trim()}><Icon name="send" /><span class="visually-hidden">{t("chat.send")}</span></button>
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
    scrollbar-width: thin;
  }

  .list-head {
    display: flex;
    gap: var(--space-2);
  }

  .new {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: var(--target);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-weight: 600;
    cursor: pointer;
  }

  .new:hover {
    border-color: var(--color-accent);
    color: var(--color-accent-text);
  }

  .icon {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: var(--target);
    height: var(--target);
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--color-text-muted);
    cursor: pointer;
  }

  .icon:hover:not(:disabled) {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  .icon:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }

  .close,
  .open-list {
    display: none;
  }

  .list ul {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .list li {
    display: flex;
    align-items: center;
    border-radius: var(--radius-md);
  }

  .list li:hover,
  .list li:focus-within {
    background: var(--color-surface-raised);
  }

  .list li:has(.entry[aria-current="true"]) {
    background: var(--color-accent-soft);
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

  .entry[aria-current="true"] {
    color: var(--color-accent-text);
    font-weight: 650;
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

  /* With a mouse, the delete button appears when the line is pointed at or reached with the keyboard; on a touch screen it is always there. */
  @media (hover: hover) {
    .remove {
      opacity: 0;
    }

    .list li:hover .remove,
    .list li:focus-within .remove {
      opacity: 1;
    }
  }

  .remove:hover:not(:disabled) {
    background: transparent;
    color: var(--color-danger);
  }

  .empty {
    padding: var(--space-2);
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
    min-height: 3.5rem;
    padding: var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }

  h1 {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: var(--text-md);
    font-weight: 650;
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
    min-height: 2.5rem;
    max-width: 14rem;
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    color: var(--color-text);
    cursor: pointer;
  }

  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    scrollbar-width: thin;
  }

  .welcome {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    max-width: 38rem;
    min-height: 100%;
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
    text-align: center;
    color: var(--color-text-muted);
  }

  .welcome h2 {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1.2;
    color: var(--color-text);
  }

  .suggestions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
    width: 100%;
    margin: var(--space-4) 0 0;
    padding: 0;
    list-style: none;
  }

  .chip {
    width: 100%;
    min-height: 3.5rem;
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    color: var(--color-text);
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
  }

  .chip:hover {
    border-color: var(--color-accent);
    background: var(--color-accent-soft);
  }

  .banner,
  .hint {
    max-width: var(--measure);
    margin: var(--space-3) auto 0;
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
    max-height: 70%;
    margin: 0 auto;
    padding: var(--space-2) var(--space-4) var(--space-3);
    overflow-y: auto;
  }

  .hint {
    max-width: none;
    margin: 0;
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
    padding: var(--space-4);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    box-shadow: var(--shadow-raised);
  }

  .card-head {
    font-size: var(--text-xs);
    font-weight: 650;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--color-accent-text);
  }

  .card-title {
    font-weight: 650;
  }

  .pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .card pre {
    max-height: 14rem;
    margin: 0;
    padding: var(--space-3);
    overflow: auto;
    border-radius: var(--radius-md);
    background: var(--color-code-bg);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }

  /* The field and its button are one rounded box; the box shows the focus of the field. */
  .composer {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-xl);
    background: var(--color-surface);
    box-shadow: var(--shadow-raised);
  }

  .composer:focus-within {
    border-color: var(--color-accent);
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--color-accent) 35%, transparent),
      var(--shadow-raised);
  }

  textarea {
    flex: 1;
    min-width: 0;
    min-height: var(--target);
    max-height: 12rem;
    padding: 0.6rem 0;
    border: 0;
    outline: none;
    background: transparent;
    resize: none;
    field-sizing: content;
  }

  .round {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: var(--target);
    height: var(--target);
    border: 0;
    border-radius: var(--radius-pill);
    cursor: pointer;
  }

  .send {
    background: var(--color-accent);
    color: var(--color-on-accent);
  }

  .send:hover:not(:disabled) {
    background: var(--color-accent-hover);
  }

  .send:disabled {
    background: var(--color-surface-raised);
    color: var(--color-text-muted);
    cursor: not-allowed;
  }

  .stop {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .meter {
    min-height: 1.4em;
    font-size: var(--text-xs);
    text-align: center;
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
    }

    .model span {
      display: none;
    }

    select {
      max-width: 9rem;
    }
  }

  @media (max-width: 520px) {
    header {
      padding: var(--space-2);
    }

    .suggestions {
      grid-template-columns: minmax(0, 1fr);
    }

    .welcome h2 {
      font-size: 1.4rem;
    }
  }
</style>
