<script lang="ts">
  // The Chat screen: the conversations, the one that is open, the answer as it is written, and what Lutin asks before it acts.
  import { onMount } from "svelte";
  import AttachmentBar from "../components/AttachmentBar.svelte";
  import Changes from "../components/Changes.svelte";
  import Icon from "../components/Icon.svelte";
  import Options from "../components/Options.svelte";
  import Thread from "../components/Thread.svelte";
  import { api, ApiError, streamTurn, upload } from "../lib/api";
  import { fromStored, MAX_DOCUMENTS, MAX_IMAGES, kindOf, refusal, turnFields, uploading, type Attachment } from "../lib/attachments";
  import { conversationOf } from "../lib/address";
  import { markOf, markSeen, readSeen } from "../lib/marks";
  import { choiceValue, parseChoice, selector, type MachinesView } from "../lib/machines";
  import { approvalPath, byMachine, conversationPath, uploadPath, type Listed } from "../lib/place";
  import { t } from "../lib/messages";
  import { applyEvent, elsewhereNotice, newTurn, storedToItems, type Item, type LiveTurn, type Sent } from "../lib/turn";
  import type { Conversation, ConversationOptions, ConversationSummary, Models, Settings, Status, TurnState } from "../lib/types";

  let { status, onchanged }: { status: Status | null; onchanged: () => void } = $props();

  let conversations = $state<ConversationSummary[]>([]);
  let remote = $state<Listed[]>([]); // the conversations of the paired machines that grant « lead » (ADR 0016, stage 6)
  let where = $state(""); // the machine that holds the open conversation: "" for this one
  const hosts = $derived(byMachine(remote));
  let query = $state(""); // what is searched in the conversations (titles and texts, GET /conversations?q=)
  let found = $state<(ConversationSummary & { extract: string })[] | null>(null);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let seen = $state<Record<string, string>>(readSeen()); // when each conversation was last seen, in this browser
  let activeNow = $state<string[]>([]);
  let waitingNow = $state<string[]>([]);
  let conversation = $state<Conversation | null>(null);
  let models = $state<Models | null>(null);
  let paired = $state<MachinesView | null>(null); // who answers by default and the names of the paired machines (GET /machines never waits)
  const choices = $derived(models ? selector(models.models.map((model) => model.name), models.current, models.remote ?? [], paired) : null);
  let live = $state<LiveTurn | null>(null);
  let pending = $state<({ text: string } & Sent) | null>(null);
  let attachments = $state<Attachment[]>([]);
  let counter = 0;
  let draft = $state("");
  let problem = $state("");
  let listOpen = $state(false);
  let scroller = $state<HTMLElement | null>(null);
  let box = $state<HTMLTextAreaElement | null>(null);
  let renaming = $state(false);
  let options = $state<ConversationOptions | null>(null);
  let optionsToSend = $state<Partial<ConversationOptions>>({}); // chosen before the conversation exists: sent when the first message creates it
  let titleDraft = $state("");
  let changesTick = $state(0); // moved at the end of each turn: the changes of the last request are read again
  let titleBox = $state<HTMLInputElement | null>(null);
  let editing = $state<number | null>(null); // the stored position of the message being rewritten
  let cut = $state<number | null>(null); // while the new answer is written, what followed that message is no longer shown

  const SUGGESTIONS = ["chat.suggest_explain", "chat.suggest_write", "chat.suggest_fix", "chat.suggest_summarise"] as const;

  /** Reads the open conversation again from the machine that holds it: after an undo, or a produced file or image deleted from the thread. */
  async function reloadConversation(): Promise<void> {
    const id = conversation?.id;
    if (id) conversation = await api<Conversation>("GET", conversationPath(where, id));
  }

  const items = $derived(storedToItems((conversation?.messages ?? []).slice(0, cut ?? undefined)));
  let elsewhere = $state(false); // an answer is being written in this conversation, but not by this page (it was reloaded, or another device sent it)
  let elsewhereTurn = $state<TurnState | undefined>(undefined); // where that turn is, when the server says it: waiting for an approval this page cannot show, stalled, being stopped
  let watcher: ReturnType<typeof setInterval> | undefined;
  const busy = $derived(live !== null || elsewhere);

  function stopWatching(): void {
    if (watcher !== undefined) clearInterval(watcher);
    watcher = undefined;
    elsewhere = false;
    elsewhereTurn = undefined;
  }

  async function runningElsewhere(id: string): Promise<boolean> {
    const current = await api<Status>("GET", "/status").catch(() => null);
    elsewhereTurn = current?.turns?.find((turn) => turn.conversation === id);
    return current?.active_turns.includes(id) ?? false;
  }

  /** After opening a conversation whose answer is still being written: wait for its end, then read what was stored. */
  async function watch(id: string): Promise<void> {
    stopWatching();
    if (live !== null || !(await runningElsewhere(id))) return;
    elsewhere = true;
    watcher = setInterval(async () => {
      if (conversation?.id !== id) return stopWatching();
      if (await runningElsewhere(id)) return;
      stopWatching();
      const stored = await api<Conversation>("GET", `/conversations/${encodeURIComponent(id)}`).catch(() => null);
      if (stored && conversation?.id === id) conversation = stored;
      await loadList().catch(() => undefined);
      onchanged();
    }, 2000);
  }

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
    const [here, others] = await Promise.all([
      api<{ conversations: ConversationSummary[] }>("GET", "/conversations"),
      api<{ conversations: { machine: string; machine_name: string; id: string; title: string }[] }>("GET", "/machines/conversations").catch(() => ({ conversations: [] })),
    ]);
    conversations = here.conversations;
    remote = others.conversations.map((entry) => ({ id: entry.id, title: entry.title, pinned: false, machine: entry.machine, machine_name: entry.machine_name }));
  }

  function onSearch(): void {
    clearTimeout(searchTimer);
    const words = query.trim();
    if (!words) {
      found = null;
      return;
    }
    searchTimer = setTimeout(async () => {
      const answer = await api<{ conversations: (ConversationSummary & { extract: string })[] }>("GET", "/conversations?q=" + encodeURIComponent(words)).catch(() => null);
      if (answer && query.trim() === words) found = answer.conversations;
    }, 250);
  }

  /** The turns running and the approvals waiting, for the marks of the list; a turn that ended reads the list again (its date changed). */
  async function followTurns(): Promise<void> {
    const now = await api<Status>("GET", "/status").catch(() => null);
    if (!now) return;
    const ended = activeNow.some((id) => !now.active_turns.includes(id));
    activeNow = now.active_turns;
    waitingNow = now.pending_approvals;
    if (ended) await loadList().catch(() => undefined);
  }

  async function loadModels(): Promise<void> {
    const [found, view] = await Promise.all([api<Models>("GET", "/models"), api<MachinesView>("GET", "/machines").catch(() => null)]);
    models = found;
    paired = view;
  }

  /** What a new conversation starts with: the settings of the machine, and the two automatic approvals off. */
  async function newConversationOptions(): Promise<ConversationOptions> {
    const settings = await api<Settings>("GET", "/settings");
    return { mode: settings.mode, thinking: settings.thinking, web: settings.web, dry_run: settings.dry_run, auto_approve_writes: false, auto_approve_commands: false, num_predict: settings.num_predict, mission_hours: 8 };
  }

  async function changeOptions(patch: Partial<ConversationOptions>): Promise<void> {
    if (options) options = { ...options, ...patch };
    if (conversation === null) {
      optionsToSend = { ...optionsToSend, ...patch };
      return;
    }
    const id = conversation.id;
    await guarded(async () => {
      try {
        options = await api<ConversationOptions>("PATCH", `/conversations/${encodeURIComponent(id)}/options`, patch);
      } catch (cause) {
        // The change was shown at once; the server did not keep it: what is on screen must be what the server holds, above all for an approval.
        options = await api<ConversationOptions>("GET", `/conversations/${encodeURIComponent(id)}/options`).catch(() => options);
        throw cause;
      }
    });
  }

  /** Opens a conversation of this machine, or of the paired machine `machine`: that one keeps it, runs its turns and has its own options. */
  async function open(id: string, machine = ""): Promise<void> {
    await guarded(async () => {
      conversation = await api<Conversation>("GET", conversationPath(machine, id));
      where = machine;
      options = machine ? null : await api<ConversationOptions>("GET", `/conversations/${encodeURIComponent(id)}/options`);
      optionsToSend = {};
      attachments = [];
      listOpen = false;
      renaming = false;
      cancelEdit();
      history.replaceState(null, "", machine ? "#/chat" : "#/chat/" + id); // a reload or a bookmark opens it again (one of another machine is not kept)
      if (!machine && conversation) seen = markSeen(id, conversation.updated_at);
      if (machine) stopWatching();
      else await watch(id);
    });
  }

  function startNew(): void {
    stopWatching();
    conversation = null;
    where = "";
    problem = "";
    history.replaceState(null, "", "#/chat");
    listOpen = false;
    renaming = false;
    optionsToSend = {};
    attachments = [];
    cancelEdit();
    void guarded(async () => {
      options = await newConversationOptions();
    });
  }

  function startRename(): void {
    if (!conversation) return;
    titleDraft = conversation.title;
    renaming = true;
  }

  async function saveRename(): Promise<void> {
    if (!renaming) return; // Enter then the loss of focus: saved once
    renaming = false;
    const current = conversation;
    const title = titleDraft.trim();
    if (!current || !title || title === current.title) return;
    await guarded(async () => {
      conversation = await api<Conversation>("PATCH", conversationPath(where, current.id), { title });
      await loadList();
    });
  }

  function onTitleKey(event: KeyboardEvent): void {
    if (event.key === "Escape") renaming = false;
  }

  async function togglePin(): Promise<void> {
    const current = conversation;
    if (!current) return;
    await guarded(async () => {
      conversation = await api<Conversation>("PATCH", conversationPath(where, current.id), { pinned: !current.pinned });
      await loadList();
    });
  }

  function startEdit(item: Extract<Item, { role: "user" }>): void {
    const stored = conversation?.messages[item.index];
    editing = item.index;
    draft = item.text;
    attachments = stored ? fromStored(stored) : []; // answering again from this message needs what was sent with it
    box?.focus();
  }

  /** Answers again from the last request: the same text and files, as an edit of that message that is sent at once. */
  function regenerate(): void {
    const last = [...items].reverse().find((item): item is Extract<Item, { role: "user" }> => item.role === "user");
    if (!last || busy) return;
    startEdit(last);
    void send();
  }

  function cancelEdit(): void {
    if (editing !== null) {
      draft = "";
      attachments = [];
    }
    editing = null;
  }

  async function addFiles(files: File[]): Promise<void> {
    for (const file of files) {
      const why = refusal(attachments, file);
      if (why !== null) {
        problem = why === "too_many" ? t("chat.attach_too_many", MAX_IMAGES, MAX_DOCUMENTS) : why === "too_big" ? t("chat.attach_too_big", file.name) : t("chat.attach_empty", file.name);
        continue;
      }
      const kind = kindOf(file);
      const key = "upload-" + ++counter;
      attachments = [...attachments, { key, kind, name: file.name, id: "", state: "uploading" }];
      try {
        const done = kind === "image" ? await upload<{ id: string }>(uploadPath(where, "images"), file) : await upload<{ id: string; name: string }>(uploadPath(where, "attachments"), file, file.name);
        attachments = attachments.map((item) => (item.key === key ? { ...item, id: done.id, state: "ready" } : item));
      } catch (cause) {
        attachments = attachments.filter((item) => item.key !== key);
        problem = explain(cause);
      }
    }
  }

  function removeAttachment(key: string): void {
    attachments = attachments.filter((item) => item.key !== key);
  }

  function onPaste(event: ClipboardEvent): void {
    const files = Array.from(event.clipboardData?.files ?? []);
    if (files.length) {
      event.preventDefault(); // a picture or a file pasted is attached; pasted text stays text
      void addFiles(files);
    }
  }

  function onDrop(event: DragEvent): void {
    event.preventDefault();
    void addFiles(Array.from(event.dataTransfer?.files ?? []));
  }

  async function remove(entry: { id: string; title: string }, machine = ""): Promise<void> {
    if (!confirm(t("chat.delete_confirm", entry.title || t("chat.untitled")))) return;
    await guarded(async () => {
      await api("DELETE", conversationPath(machine, entry.id));
      if (conversation?.id === entry.id && where === machine) (conversation = null), (where = "");
      await loadList();
    });
  }

  async function send(): Promise<void> {
    const message = draft.trim();
    if (!message || busy || uploading(attachments)) return;
    await guarded(async () => {
      if (conversation === null) {
        conversation = await api<Conversation>("POST", "/conversations", {});
        history.replaceState(null, "", "#/chat/" + conversation.id); // the first message makes the conversation: its address too
        if (Object.keys(optionsToSend).length) {
          options = await api<ConversationOptions>("PATCH", `/conversations/${encodeURIComponent(conversation.id)}/options`, optionsToSend);
          optionsToSend = {};
        }
      }
      const id = conversation.id;
      const at = where; // a new conversation is always one of this machine
      const from = editing;
      const sent = attachments;
      draft = "";
      editing = null;
      attachments = [];
      cut = from;
      pending = { text: message, images: sent.filter((item) => item.kind === "image").map((item) => item.id), files: sent.filter((item) => item.kind === "document").map((item) => ({ id: item.id, name: item.name })) };
      live = newTurn();
      try {
        await streamTurn(conversationPath(at, id), { message, ...(from === null ? {} : { replace_from: from }), ...turnFields(sent) }, (event) => {
          if (live) live = applyEvent(live, event);
        });
      } catch (cause) {
        if (live !== null && live.blocks.length === 0) {
          draft = message; // refused before anything was written: the message is given back, with its files, still as an edit if it was one
          editing = from;
          attachments = sent;
        }
        throw cause;
      } finally {
        // What is stored is the truth: the conversation is read again, whether the stream ended well or was cut.
        const stored = await api<Conversation>("GET", conversationPath(at, id)).catch(() => null);
        if (stored && where === at) conversation = stored;
        if (stored && !at) seen = markSeen(id, stored.updated_at);
        cut = null;
        pending = null;
        live = null;
        changesTick += 1;
        await loadList().catch(() => undefined);
        onchanged();
      }
    });
  }

  async function stop(): Promise<void> {
    const id = conversation?.id;
    if (id) await guarded(async () => void (await api("POST", conversationPath(where, id) + "/stop", {})));
  }

  async function answerApproval(approved: boolean, remember: "once" | "chat" | "always" = "once"): Promise<void> {
    const approval = live?.approval;
    if (!approval) return;
    await guarded(async () => {
      await api("POST", approvalPath(where, approval.id), { approved, remember });
      if (live) live = { ...live, approval: null };
    });
  }

  async function answerMemory(choice: "summary" | "file"): Promise<void> {
    const id = conversation?.id;
    if (!id) return;
    await guarded(async () => {
      await api("POST", conversationPath(where, id) + "/memory-choice", { choice });
      if (live) live = { ...live, memoryChoice: false };
    });
  }

  async function chooseModel(event: Event): Promise<void> {
    const { machine, model } = parseChoice((event.currentTarget as HTMLSelectElement).value); // a model of another machine: that machine answers (as on the old page)
    await guarded(async () => {
      await api("PATCH", "/settings", { model, machine });
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
    if (renaming) titleBox?.focus();
  });

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
      options = await newConversationOptions();
    });
    const named = conversationOf(location.hash);
    if (named) void open(named);
    void followTurns();
    const marks = setInterval(() => void followTurns(), 5000);
    return () => {
      stopWatching();
      clearInterval(marks);
      clearTimeout(searchTimer);
    };
  });
</script>

<div class="chat" class:list-open={listOpen}>
  <aside class="list" aria-label={t("chat.conversations")}>
    <div class="list-head">
      <button type="button" class="new" onclick={startNew}><Icon name="plus" size={18} /><span>{t("chat.new")}</span></button>
      <button type="button" class="icon close" onclick={() => (listOpen = false)}><Icon name="close" /><span class="visually-hidden">{t("chat.hide_list")}</span></button>
    </div>
    <label class="visually-hidden" for="conversation-search">{t("chat.search")}</label>
    <input id="conversation-search" class="search" type="search" placeholder={t("chat.search")} autocomplete="off" bind:value={query} oninput={onSearch} />
    {#if query.trim()}
      {#if found && found.length === 0}<p class="empty">{t("chat.search_none")}</p>{/if}
      {#if found && found.length}
        <ul class="found" aria-label={t("chat.search_results")}>
          {#each found as entry (entry.id)}
            <li>
              <button type="button" class="entry" onclick={() => open(entry.id)}>
                <span class="title">{entry.title || t("chat.untitled")}</span>
                {#if entry.extract}<span class="extract">{entry.extract}</span>{/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    {:else if conversations.length === 0}
      <p class="empty">{t("chat.empty_list")}</p>
    {:else}
      <ul>
        {#each conversations as entry (entry.id)}
          {@const mark = markOf(entry.id, entry.updated_at, activeNow, waitingNow, seen, where === "" ? (conversation?.id ?? null) : null)}
          <li>
            <button type="button" class="entry" aria-current={conversation?.id === entry.id && where === "" ? "true" : undefined} onclick={() => open(entry.id)}>
              <span class="title">{entry.title || t("chat.untitled")}</span>
              {#if mark}<span class={"mark " + mark}>{t(("chat.mark." + mark) as "chat.mark.working")}</span>{/if}
              {#if entry.pinned}<span class="tag"><Icon name="pin" size={14} /><span class="visually-hidden">{t("chat.pinned")}</span></span>{/if}
            </button>
            <button type="button" class="icon remove" onclick={() => remove(entry)} disabled={busy && conversation?.id === entry.id && where === ""}>
              <Icon name="trash" size={16} /><span class="visually-hidden">{t("chat.delete")} : {entry.title || t("chat.untitled")}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#each hosts as host (host.machine)}
      <p class="host" id={"host-" + host.machine}><Icon name="models" size={16} /><span>{host.name}</span></p>
      <ul class="remote" aria-labelledby={"host-" + host.machine}>
        {#each host.conversations as entry (entry.id)}
          <li>
            <button type="button" class="entry" aria-current={conversation?.id === entry.id && where === host.machine ? "true" : undefined} onclick={() => open(entry.id, host.machine)}>
              <span class="title">{entry.title || t("chat.untitled")}</span>
            </button>
            <button type="button" class="icon remove" onclick={() => remove(entry, host.machine)} disabled={busy && conversation?.id === entry.id && where === host.machine}>
              <Icon name="trash" size={16} /><span class="visually-hidden">{t("chat.delete")} : {entry.title || t("chat.untitled")}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/each}
  </aside>

  <section class="main">
    <header>
      <button type="button" class="icon open-list" onclick={() => (listOpen = true)}><Icon name="menu" /><span class="visually-hidden">{t("chat.show_list")}</span></button>
      {#if renaming}
        <form class="rename" onsubmit={(event) => (event.preventDefault(), void saveRename())}>
          <label class="visually-hidden" for="title">{t("chat.title")}</label>
          <input id="title" maxlength="120" bind:value={titleDraft} bind:this={titleBox} onkeydown={onTitleKey} onblur={saveRename} />
        </form>
      {:else}
        <h1>{conversation?.title || t("chat.untitled")}</h1>
        {#if conversation}
          <button type="button" class="icon rename-button" onclick={startRename} disabled={busy}><Icon name="pencil" size={18} /><span class="visually-hidden">{t("chat.rename")}</span></button>
          <button type="button" class="icon pin-button" aria-pressed={conversation.pinned} onclick={togglePin} disabled={busy}>
            <Icon name="pin" size={18} /><span class="visually-hidden">{t(conversation.pinned ? "chat.unpin" : "chat.pin")}</span>
          </button>
        {/if}
      {/if}
      {#if where}
        <p class="model on-host" title={t("chat.on_machine_help")}>{t("chat.on_machine", remote.find((entry) => entry.machine === where)?.machine_name ?? paired?.machines.find((entry) => entry.id === where)?.name ?? "")}</p>
      {:else}
      <label class="model">
        <span>{t("chat.model")}</span>
        <select onchange={chooseModel} disabled={busy || !choices || (choices.local.length === 0 && choices.groups.length === 0)} title={choices?.missing?.off ? t("chat.machine_off_help", choices.missing.name) : undefined}>
          {#if !choices || (choices.local.length === 0 && choices.groups.length === 0)}
            <option>{t("chat.no_model")}</option>
          {:else}
            {#if choices.missing}
              <option value={choices.current} selected>{choices.missing.off ? t("chat.machine_off", choices.missing.model, choices.missing.name) : choices.missing.model}</option>
            {/if}
            {#snippet here()}
              {#each choices!.local as name (name)}
                <option value={choiceValue("", name)} selected={choiceValue("", name) === choices!.current}>{name}</option>
              {/each}
            {/snippet}
            {#if choices.groups.length}
              {#if choices.local.length}<optgroup label={t("chat.this_machine")}>{@render here()}</optgroup>{/if}
              {#each choices.groups as group (group.machine)}
                <optgroup label={group.name}>
                  {#each group.models as name (name)}
                    <option value={choiceValue(group.machine, name)} selected={choiceValue(group.machine, name) === choices.current}>{name}</option>
                  {/each}
                </optgroup>
              {/each}
            {:else}
              {@render here()}
            {/if}
          {/if}
        </select>
      </label>
      {/if}
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
        <Thread {items} {pending} {live} onedit={busy ? undefined : startEdit} onregenerate={busy ? undefined : regenerate} machine={where} conversation={conversation?.id ?? ""}
          canOpen={!where && !!status?.can_open_files} canDelete={!where && !!status?.access.can_configure} onproduced={reloadConversation} />
        {#if elsewhere}<p class="elsewhere" role="status">{t(elsewhereNotice(elsewhereTurn))}</p>{/if}
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
            <button type="button" class="button primary" onclick={() => answerApproval(true)}>{live.approval.canRemember && !where ? t("approval.once") : t("approval.approve")}</button>
            {#if live.approval.canRemember && !where}
              <button type="button" class="button" onclick={() => answerApproval(true, "chat")}>{t("approval.chat")}</button>
              <button type="button" class="button" onclick={() => answerApproval(true, "always")}>{t("approval.always")}</button>
            {/if}
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
      {#if conversation && !where}
        <Changes conversation={conversation.id} tick={changesTick} onundone={reloadConversation} />
      {/if}
      {#if options}<Options {options} onchange={changeOptions} />{/if}
      {#if editing !== null}
        <p class="editing"><span>{t("chat.editing")}</span><button type="button" class="link" onclick={cancelEdit}>{t("chat.cancel")}</button></p>
      {/if}
      <form class="composer" onsubmit={onSubmit} ondragover={(event) => event.preventDefault()} ondrop={onDrop}>
        <AttachmentBar {attachments} onadd={addFiles} onremove={removeAttachment} disabled={busy} machine={where} />
        <label class="visually-hidden" for="message">{t("chat.message")}</label>
        <textarea id="message" rows="1" placeholder={t("chat.placeholder")} aria-describedby="keys" bind:value={draft} bind:this={box} onkeydown={onKey} onpaste={onPaste}></textarea>
        {#if busy}
          <button type="button" class="round stop" onclick={stop}><Icon name="stop" /><span class="visually-hidden">{t("chat.stop")}</span></button>
        {:else}
          <button type="submit" class="round send" disabled={!draft.trim() || uploading(attachments)}><Icon name="send" /><span class="visually-hidden">{t("chat.send")}</span></button>
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
    display: inline-flex;
    flex: none;
    color: var(--color-accent-text);
  }

  .entry .title {
    flex: 1;
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

  .search {
    width: 100%;
    min-height: var(--target);
    margin: var(--space-2) 0;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .found .entry {
    flex-direction: column;
    align-items: flex-start;
  }

  .extract {
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    white-space: normal;
  }

  .mark {
    flex: none;
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .mark.waiting {
    background: var(--color-warning-soft);
    color: var(--color-text);
  }

  .empty {
    padding: var(--space-2);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  /* The conversations held by another machine, under its name. */
  .host {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-4) 0 var(--space-1);
    padding: 0 var(--space-2);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    font-weight: 600;
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

  .rename {
    display: flex;
    flex: 1;
    min-width: 0;
  }

  .rename input {
    flex: 1;
    min-width: 0;
    min-height: 2.5rem;
    padding: 0 var(--space-3);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-weight: 650;
  }

  .pin-button[aria-pressed="true"] {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .editing {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-accent-soft);
    font-size: var(--text-sm);
  }

  .link {
    min-height: 2rem;
    padding: 0 var(--space-2);
    border: 0;
    background: transparent;
    color: var(--color-accent-text);
    font-weight: 650;
    text-decoration: underline;
    cursor: pointer;
  }

  .model {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--color-text-muted);
  }

  .on-host {
    margin: 0 0 0 auto;
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-weight: 600;
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
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-2);
    padding: var(--space-2);
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
    min-width: 8rem;
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

  .elsewhere {
    margin: var(--space-3) 0 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-size: var(--text-sm);
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

    /* The label of the model list is hidden from the eyes but kept for screen readers (display: none would remove the name of the list). */
    .model span {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
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
