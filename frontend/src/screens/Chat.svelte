<script lang="ts">
  // The Chat screen: the conversations, the one that is open, the answer as it is written, and what Lutin asks before it acts.
  import { onMount } from "svelte";
  import AttachmentBar from "../components/AttachmentBar.svelte";
  import Changes from "../components/Changes.svelte";
  import Icon from "../components/Icon.svelte";
  import LutinFace from "../components/LutinFace.svelte";
  import { passMood } from "../lib/lutin_mood";
  import Options from "../components/Options.svelte";
  import Thread from "../components/Thread.svelte";
  import { api, ApiError, streamTurn, upload } from "../lib/api";
  import { fromStored, MAX_DOCUMENTS, MAX_IMAGES, kindOf, refusal, turnFields, uploading, type Attachment } from "../lib/attachments";
  import { conversationOf } from "../lib/address";
  import { markOf, markSeen, readSeen, tabTitle } from "../lib/marks";
  import { choiceValue, parseChoice, selector, type MachinesView } from "../lib/machines";
  import { approvalPath, byMachine, conversationPath, uploadPath, type Listed } from "../lib/place";
  import { t, type MessageKey } from "../lib/messages";
  import { byUse } from "../lib/model_card";
  import { applyEvent, elsewhereNotice, newTurn, storedToItems, type Item, type LiveTurn, type Sent } from "../lib/turn";
  import ConversationTools from "../components/ConversationTools.svelte";
  import { COMMANDS, MODE_NAMES, onOff, parse, suggest as suggestCommands, type Parsed } from "../lib/slash";
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
  let queue = $state<string[]>([]); // messages typed while an answer runs: sent one by one after it
  let projectCommands = $state<{ name: string; description: string }[]>([]); // the commands of a Claude project in the work folder
  let commandNotice = $state(""); // what a « / » command did
  let showHelp = $state(false);
  let toolsOpen = $state(false);
  let starting = $state(false); // the engine asked to start from the banner
  let verify = $state<{ query: string; removed: string[]; reasons: string[]; results: { title: string; url: string; extract: string; domain: string }[] } | null>(null);
  let sentBefore = $state<string[]>([]); // what was sent from this page, for ↑ in an empty box
  let recallAt = -1; // the tools of the open conversation (memory, handover, export, folders)
  let mission = $state<{ name: string; state: string } | null>(null); // the mission written in the open conversation, if any
  let models = $state<Models | null>(null);
  let paired = $state<MachinesView | null>(null); // who answers by default and the names of the paired machines (GET /machines never waits)
  const choices = $derived(models ? selector(models.models.map((model) => model.name), models.current, models.remote ?? [], paired) : null);
  const localByUse = $derived(choices ? byUse(choices.local) : []); // the models of this machine by use, then family and size
  let live = $state<LiveTurn | null>(null);
  let pending = $state<({ text: string } & Sent) | null>(null);
  // The conversation the answer being written belongs to. Another one may be opened meanwhile: the answer is shown only in its own, and its end
  // does not replace the one the person is reading (the old page wrote it into whatever conversation was open).
  let liveAt = $state<{ id: string; at: string } | null>(null);
  const liveHere = $derived(liveAt !== null && conversation?.id === liveAt.id && where === liveAt.at);
  const shownLive = $derived(liveHere ? live : null);
  // Under the field, as LM Studio does: the figures of the answer being written, otherwise those of the last answer of this conversation.
  const meterContext = $derived(shownLive ? shownLive.tokens : (conversation?.context ?? null));
  const meterSpeed = $derived(shownLive ? shownLive.tokensPerSecond : (conversation?.speed?.write_tokens_per_s ?? null));
  const shownPending = $derived(liveHere ? pending : null);
  let attachments = $state<Attachment[]>([]);
  let counter = 0;
  let draft = $state("");
  const suggested = $derived(suggestCommands(draft, projectCommands.map((command) => command.name)));
  let problem = $state("");
  let listOpen = $state(false);
  let scroller = $state<HTMLElement | null>(null);
  const FOLLOW_MARGIN = 80; // pixels: closer than this to the end counts as « at the end »
  let following = $state(true);
  let box = $state<HTMLTextAreaElement | null>(null);
  type InMemory = { known: boolean; loaded: boolean; state?: "loaded" | "loading" | "not_loaded" | "unknown"; loading_bytes?: number };
  let inMemory = $state<InMemory | null>(null);
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

  const items = $derived(storedToItems((conversation?.messages ?? []).slice(0, liveHere ? (cut ?? undefined) : undefined)));
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
  let doneUnseen = $state(false); // an answer ended while the tab was hidden: the tab says so until the person comes back
  const baseTitle = document.title || "Lutin";
  $effect(() => {
    document.title = tabTitle(baseTitle, live !== null && liveAt ? [...new Set([...activeNow, liveAt.id])] : activeNow, waitingNow, doneUnseen);
  });

  async function followTurns(): Promise<void> {
    const now = await api<Status>("GET", "/status").catch(() => null);
    if (!now) return;
    const ended = activeNow.some((id) => !now.active_turns.includes(id));
    if (ended && document.hidden) doneUnseen = true;
    activeNow = now.active_turns;
    waitingNow = now.pending_approvals;
    if (ended) await loadList().catch(() => undefined);
  }

  async function loadModels(): Promise<void> {
    const [found, view] = await Promise.all([api<Models>("GET", "/models"), api<MachinesView>("GET", "/machines").catch(() => null)]);
    models = found;
    paired = view;
    void readLoaded();
  }

  /** The title the model gives a new conversation after its first answer (as the old page did); the first words of the message stay if it cannot. */
  async function nameConversation(id: string): Promise<void> {
    const named = await api<{ title: string; applied: boolean }>("POST", `/conversations/${encodeURIComponent(id)}/ai-title`, {}).catch(() => null);
    if (!named?.applied) return;
    if (conversation?.id === id && !where) conversation = { ...conversation, title: named.title };
    await loadList().catch(() => undefined);
  }

  /** Is the model in use in memory? Asked again every few seconds with the marks of the list, and after a turn or a change of model. `known` false: the engine cannot say, nothing is shown. */
  async function readLoaded(): Promise<void> {
    inMemory = await api<InMemory>("GET", "/models/loaded").catch(() => inMemory);
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
      toolsOpen = false;
      mission = null;
      if (!machine) void api<{ missions: { name: string; state: string; conversation: string }[] }>("GET", "/missions").then((answer) => (mission = answer.missions.find((entry) => entry.conversation === id) ?? null), () => undefined);
      if (machine) stopWatching();
      else await watch(id);
    });
  }

  function startNew(): void {
    stopWatching();
    conversation = null;
    where = "";
    problem = "";
    toolsOpen = false;
    mission = null;
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
      let fresh = false; // this message makes the conversation: once answered, it is named from what it says
      if (conversation === null) {
        fresh = true;
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
      liveAt = { id, at };
      pending = { text: message, images: sent.filter((item) => item.kind === "image").map((item) => item.id), files: sent.filter((item) => item.kind === "document").map((item) => ({ id: item.id, name: item.name })) };
      live = newTurn();
      setTimeout(() => void readLoaded(), 1000); // the turn has started on the server: the pill says « loading » at once when the model is not there
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
        // An error of the engine is a block of the turn being written, and the stored conversation does not hold it: reading it again would take the message away at once.
        // It stays above the field until the next message or another conversation.
        const failure = live?.blocks.flatMap((block) => (block.kind === "error" ? [block.message] : []))[0] ?? "";
        // What is stored is the truth: the conversation is read again, whether the stream ended well or was cut.
        const stored = await api<Conversation>("GET", conversationPath(at, id)).catch(() => null);
        if (stored && where === at && conversation?.id === id) conversation = stored;          // the person may be reading another conversation now
        if (stored && !at) seen = markSeen(id, stored.updated_at);
        if (fresh && stored && !at && !failure) void nameConversation(id);
        cut = null;
        pending = null;
        live = null;
        liveAt = null;
        if (document.hidden) doneUnseen = true; // ended while the person was in another tab
        if (failure && conversation?.id === id) problem = failure;
        passMood(failure ? "angry" : "happy"); // the logo is glad for a moment, or cross when the engine failed
        changesTick += 1;
        void readLoaded(); // a turn loads the model: the answer to « is it in memory » has changed
        await loadList().catch(() => undefined);
        onchanged();
      }
    });
  }

  async function stop(): Promise<void> {
    const id = conversation?.id;
    if (id) await guarded(async () => void (await api("POST", conversationPath(where, id) + "/stop", {})));
  }

  async function answerApproval(approved: boolean, remember: "once" | "chat" | "always" = "once", restore = false): Promise<void> {
    const approval = live?.approval;
    if (!approval) return;
    await guarded(async () => {
      await api("POST", approvalPath(where, approval.id), { approved, remember, ...(restore ? { restore_auto_approval: true } : {}) });
      if (live) live = { ...live, approval: null };
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

  async function startEngine(): Promise<void> {
    if (!status) return;
    starting = true;
    await guarded(async () => {
      await api("POST", `/engines/${encodeURIComponent(status!.engine.id)}/actions/start`, {});
      for (let tries = 0; tries < 30; tries += 1) {
        await new Promise((done) => setTimeout(done, 1000));
        const now = await api<Status>("GET", "/status").catch(() => null);
        if (now?.engine.running) break;
      }
      onchanged();
    });
    starting = false;
  }

  async function pinMessage(index: number, pinned: boolean): Promise<void> {
    const id = conversation?.id;
    if (!id || where) return;
    await guarded(async () => {
      await api("PATCH", `/conversations/${encodeURIComponent(id)}/messages/${index}`, { pinned });
      await reloadConversation();
    });
  }

  async function verifyAnswer(question: string): Promise<void> {
    await guarded(async () => void (verify = await api("POST", "/web-search/preview", { q: question.slice(0, 300) })));
  }

  function onKey(event: KeyboardEvent): void {
    if ((event.key === "ArrowUp" || event.key === "ArrowDown") && !event.shiftKey && sentBefore.length && (draft === "" || recallAt >= 0)) {
      // ↑ in an empty box brings back what was sent before, ↓ goes forward again (as a terminal does)
      event.preventDefault();
      recallAt = event.key === "ArrowUp" ? Math.min(recallAt + 1, sentBefore.length - 1) : recallAt - 1;
      draft = recallAt >= 0 ? sentBefore[sentBefore.length - 1 - recallAt] : "";
      return;
    }
    recallAt = -1;
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submitDraft();
    }
  }

  function onSubmit(event: SubmitEvent): void {
    event.preventDefault();
    submitDraft();
  }

  /** What « send » does: a « / » command is carried out here; a message typed while an answer runs waits in the queue and leaves after it. */
  function submitDraft(): void {
    const typed = draft.trim();
    if (!typed) return;
    sentBefore = [...sentBefore.filter((text) => text !== typed), typed].slice(-50);
    recallAt = -1;
    const parsed = parse(typed, projectCommands.map((command) => command.name));
    if (parsed) {
      void runCommand(parsed);
      return;
    }
    if (busy) {
      if (!attachments.length && !editing) {
        queue = [...queue, typed];
        draft = "";
      }
      return;
    }
    void send();
  }

  $effect(() => {
    // The queue leaves one message at a time, each once the previous answer has ended.
    if (!busy && queue.length && !problem) {
      const [next, ...rest] = queue;
      queue = rest;
      draft = next;
      void send();
    }
  });

  async function runCommand(parsed: Parsed): Promise<void> {
    commandNotice = "";
    showHelp = false;
    const id = conversation?.id ?? "";
    const done = (text = ""): void => {
      draft = "";
      commandNotice = text;
    };
    if (parsed.kind === "unknown") {
      commandNotice = t("slash.unknown", parsed.name);
      return;
    }
    if (parsed.kind === "project") {
      await guarded(async () => {
        draft = (await api<{ text: string }>("GET", `/project-commands/${encodeURIComponent(parsed.name)}?args=${encodeURIComponent(parsed.arg)}`)).text;
        if (!busy) await send();
      });
      return;
    }
    const arg = parsed.arg;
    const flag = onOff(arg);
    const option = { think: "thinking", web: "web", files: "auto_approve_writes", commands: "auto_approve_commands" } as const;
    switch (parsed.command) {
      case "help":
        draft = "";
        showHelp = true;
        return;
      case "new":
        done();
        startNew();
        return;
      case "stop":
        done();
        await stop();
        return;
      case "retry":
        done();
        regenerate();
        return;
      case "git":
        done();
        location.hash = "#/projects";
        return;
      case "health":
        done();
        location.hash = "#/settings/health";
        return;
      case "compact":
        if (!id || where) return done(t("slash.no_conversation"));
        await guarded(async () => {
          const answer = await api<{ before: number; after: number }>("POST", `/conversations/${encodeURIComponent(id)}/compact`, {});
          done(t("slash.compacted", answer.before, answer.after));
          await reloadConversation();
        });
        return;
      case "model":
        if (!arg) return done(t("slash.model_now", models?.current ?? ""));
        await guarded(async () => {
          await api("PATCH", "/settings", { model: arg });
          models = await api<Models>("GET", "/models");
          done(t("slash.model_set", arg));
          onchanged();
        });
        return;
      case "mode": {
        const mode = MODE_NAMES[arg.toLowerCase()];
        if (!mode) return done(t("slash.expected", "general, technical, scenario, research, chat"));
        await changeOptions({ mode: mode as ConversationOptions["mode"] });
        return done(t("slash.set", t(("opt.mode." + mode) as MessageKey)));
      }
      default:
        if (flag === null) return done(t("slash.expected", "on, off"));
        await changeOptions({ [option[parsed.command]]: flag });
        return done(t("slash.set", parsed.command + " " + (flag ? "on" : "off")));
    }
  }

  $effect(() => {
    if (renaming) titleBox?.focus();
  });

  $effect(() => {
    // Follow the answer while it is written, but only when the person is at the end: someone who scrolled up to read is left where they are, and the
    // « ↓ » button brings them back (as the old page did).
    void items;
    void shownLive;
    void shownPending;
    pinToEnd();
  });

  let pinnedTop = 0; // where the thread was last left, by the person or by pinToEnd: a scroll that does not go above it is not the person leaving the end

  function pinToEnd(): void {
    if (!scroller || !following) return;
    scroller.scrollTop = scroller.scrollHeight;
    pinnedTop = scroller.scrollTop;
  }

  $effect(() => {
    // The thread also changes size without a new message: a banner shown above it once the status is read, the dock below it growing, a block
    // drawn later. Someone at the end stays there; the size of the thread and of each piece inside it is watched for that.
    const area = scroller;
    if (!area) return;
    const sizes = new ResizeObserver(() => pinToEnd());
    const watchPieces = (): void => {
      sizes.disconnect();
      sizes.observe(area);
      for (const piece of area.children) sizes.observe(piece);
    };
    const pieces = new MutationObserver(watchPieces);
    watchPieces();
    pieces.observe(area, { childList: true });
    return () => {
      pieces.disconnect();
      sizes.disconnect();
    };
  });

  let followedId = ""; // the conversation the person is reading: a reload of the same one (every few seconds) does not bring them back to the end
  $effect(() => {
    const id = conversation?.id ?? "";
    if (id !== followedId) {
      followedId = id;
      following = true;
    }
  });

  $effect(() => {
    if (shownPending) following = true; // a message just sent: its answer is followed
  });

  function onThreadScroll(): void {
    if (!scroller) return;
    const top = scroller.scrollTop;
    // The scroll event comes a frame after pinToEnd: content that grew in between leaves the end far below without the person having moved.
    // Only going up leaves the end; coming back near it follows it again.
    if (scroller.scrollHeight - top - scroller.clientHeight < FOLLOW_MARGIN) following = true;
    else if (top < pinnedTop) following = false;
    pinnedTop = top;
  }

  function toBottom(): void {
    following = true;
    pinToEnd();
  }

  onMount(() => {
    const onNew = (): void => startNew(); // « New conversation » of the Ctrl+K palette while the Chat is open
    addEventListener("lutin-new-conversation", onNew);
    api<{ commands: { name: string; description: string }[] }>("GET", "/project-commands").then((answer) => (projectCommands = answer.commands), () => undefined);
    void guarded(async () => {
      await Promise.all([loadList(), loadModels()]);
      options = await newConversationOptions();
    });
    const named = conversationOf(location.hash);
    if (named) void open(named);
    void followTurns();
    const back = (): void => {
      if (!document.hidden) doneUnseen = false;
    };
    document.addEventListener("visibilitychange", back);
    const marks = setInterval(() => {
      void followTurns();
      void readLoaded();
    }, 5000);
    return () => {
      removeEventListener("lutin-new-conversation", onNew);
      document.removeEventListener("visibilitychange", back);
      document.title = baseTitle;
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
          {#if !where}
            <button type="button" class="button quiet tools-button" aria-expanded={toolsOpen} title={t("tools.open_hint")} onclick={() => (toolsOpen = !toolsOpen)}>{t("tools.open")}<span class="visually-hidden"> {t("tools.title")}</span></button>
          {/if}
        {/if}
      {/if}
      {#if where}
        <p class="model on-host" title={t("chat.on_machine_help")}>{t("chat.on_machine", remote.find((entry) => entry.machine === where)?.machine_name ?? paired?.machines.find((entry) => entry.id === where)?.name ?? "")}</p>
      {:else}
      {#if inMemory?.known}
        {@const loading = inMemory.state === "loading"}
        {@const loadedGb = (inMemory.loading_bytes ?? 0) / 1e9}
        <span class="memory" class:loaded={inMemory.loaded} class:loading role="status"
          title={loading ? t("chat.memory_loading_help") : inMemory.loaded ? t("chat.memory_in_help") : t("chat.memory_out_help")}><span class="dot" aria-hidden="true"></span
          >{loading ? (loadedGb >= 0.1 ? t("chat.memory_loading_gb", loadedGb.toLocaleString(undefined, { maximumFractionDigits: 1 })) : t("chat.memory_loading")) : inMemory.loaded ? t("chat.memory_in") : t("chat.memory_out")}</span>
      {/if}
      <label class="model">
        <span>{t("chat.model")}</span>
        <select onchange={chooseModel} disabled={busy || !choices || (choices.local.length === 0 && choices.groups.length === 0)} title={choices?.missing?.off ? t("chat.machine_off_help", choices.missing.name) : undefined}>
          {#if !choices || (choices.local.length === 0 && choices.groups.length === 0)}
            <option>{t("chat.no_model")}</option>
          {:else}
            {#if choices.missing}
              <option value={choices.current} selected>{choices.missing.off ? t("chat.machine_off", choices.missing.model, choices.missing.name) : choices.missing.model}</option>
            {/if}
            {#snippet option(machine: string, name: string)}
              <option value={choiceValue(machine, name)} selected={choiceValue(machine, name) === choices!.current}>{name}</option>
            {/snippet}
            {#snippet here()}
              {#each localByUse.flatMap((group) => group.names) as name (name)}{@render option("", name)}{/each}
            {/snippet}
            {#if choices.groups.length}
              {#if choices.local.length}<optgroup label={t("chat.this_machine")}>{@render here()}</optgroup>{/if}
              {#each choices.groups as group (group.machine)}
                <optgroup label={group.name}>
                  {#each byUse(group.models).flatMap((part) => part.names) as name (name)}{@render option(group.machine, name)}{/each}
                </optgroup>
              {/each}
            {:else if localByUse.length > 1}
              <!-- One machine: the models grouped by what they are for (maintainer, 2026-11-22), conversation first. -->
              {#each localByUse as group (group.use)}
                <optgroup label={t(("card.use." + group.use) as MessageKey)}>
                  {#each group.names as name (name)}{@render option("", name)}{/each}
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
    {#if toolsOpen && conversation && !where}
      <ConversationTools conversation={conversation.id} title={conversation.title || t("chat.untitled")} messages={conversation.messages} canConfigure={!!status?.access.can_configure} />
    {/if}
    {#if mission}
      <p class="mission-banner" role="status">{t("tools.mission", mission.name, t(("missions.state." + mission.state) as "missions.state.running"))} <a href="#/agents">{t("tools.mission_open")}</a></p>
    {/if}

    <div class="thread-area">
    <div class="scroll" bind:this={scroller} onscroll={onThreadScroll}>
      {#if status && !status.engine.running}
        <p class="banner">{t("chat.engine_stopped", status.engine.name)}
          {#if status.access.can_configure}<button type="button" class="link" disabled={starting} onclick={startEngine}>{starting ? t("chat.engine_starting") : t("chat.engine_start", status.engine.name)}</button>{/if}
          <a href="#/settings/health">{t("chat.engine_check")}</a></p>
      {/if}
      {#if items.length === 0 && !shownPending && !shownLive}
        <div class="welcome">
          <LutinFace mood="idle" size={64} />
          <h2>{t("chat.welcome")}</h2>
          <p>{t("chat.welcome_hint")}</p>
          <ul class="suggestions" aria-label={t("chat.suggestions")}>
            {#each SUGGESTIONS as key (key)}
              <li><button type="button" class="chip" onclick={() => suggest(t(key))}>{t(key)}</button></li>
            {/each}
          </ul>
        </div>
      {:else}
        <Thread {items} pending={shownPending} live={shownLive} onedit={busy ? undefined : startEdit} onregenerate={busy ? undefined : regenerate}
          onpin={busy || where ? undefined : pinMessage} onverify={status?.offline ? undefined : verifyAnswer} machine={where} conversation={conversation?.id ?? ""}
          canOpen={!where && !!status?.can_open_files} canDelete={!where && !!status?.access.can_configure} onproduced={reloadConversation} modelLoaded={inMemory?.known ? inMemory.loaded : null} />
        {#if elsewhere}<p class="elsewhere" role="status">{t(elsewhereNotice(elsewhereTurn))}</p>{/if}
        {#if live !== null && !liveHere}<p class="elsewhere" role="status">{t("chat.answer_in_other")}</p>{/if}
      {/if}
    </div>
    {#if !following && (items.length || shownLive)}
      <button type="button" class="to-bottom" class:writing={busy} onclick={toBottom} aria-label={t("chat.to_bottom")} title={t("chat.to_bottom")}><Icon name="down" size={20} /></button>
    {/if}
    </div>

    <div class="dock">
      {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
      {#if verify}
        <section class="verify card" aria-labelledby="verify-title">
          <p class="card-head" id="verify-title">{t("verify.title", verify.query)} <button type="button" class="link" onclick={() => (verify = null)}>{t("verify.close")}</button></p>
          <p class="hint">{t("verify.help")}</p>
          {#if verify.removed.length}<p class="hint">{t("verify.removed", verify.removed.join(", "))}</p>{/if}
          {#if verify.results.length === 0}<p class="hint">{verify.reasons.join(" ; ") || t("olib.none")}</p>{/if}
          <ul>{#each verify.results as result (result.url)}<li><a href={result.url} target="_blank" rel="noopener noreferrer">{result.title}</a> <span class="hint">{result.domain}</span><br />{result.extract}</li>{/each}</ul>
        </section>
      {/if}
      {#if shownLive?.autoApprovalSuspended}<p class="hint">{t("approval.suspended", shownLive.autoApprovalSuspended)}</p>{/if}
      {#if shownLive?.approval}
        <div class="card" role="group" aria-label={t("approval.heading")}>
          <p class="card-head">{t("approval.heading")}</p>
          <p class="card-title">{shownLive.approval.title}</p>
          {#if shownLive.approval.detail}<p class="pre">{shownLive.approval.detail}</p>{/if}
          {#if shownLive.approval.diff}<pre>{shownLive.approval.diff}</pre>{/if}
          {#if shownLive.approval.reason}<p class="hint">{shownLive.approval.reason}</p>{/if}
          <div class="actions">
            <button type="button" class="button primary" onclick={() => answerApproval(true)}>{shownLive.approval.canRemember && !where ? t("approval.once") : t("approval.approve")}</button>
            {#if shownLive.approval.canRemember && !where}
              <button type="button" class="button" onclick={() => answerApproval(true, "chat")}>{t("approval.chat")}</button>
              <button type="button" class="button" onclick={() => answerApproval(true, "always")}>{t("approval.always")}</button>
            {/if}
            {#if shownLive.autoApprovalSuspended}<button type="button" class="button" onclick={() => answerApproval(true, "once", true)}>{t("approval.restore")}</button>{/if}
            <button type="button" class="button danger" onclick={() => answerApproval(false)}>{t("approval.refuse")}</button>
          </div>
        </div>
      {/if}
      {#if conversation && !where}
        <Changes conversation={conversation.id} tick={changesTick} onundone={reloadConversation} />
      {/if}
      {#if options}<Options {options} offline={!!status?.offline} onchange={changeOptions} />{/if}
      {#if editing !== null}
        <p class="editing"><span>{t("chat.editing")}</span><button type="button" class="link" onclick={cancelEdit}>{t("chat.cancel")}</button></p>
      {/if}
      {#if suggested.length}
        <ul class="slash" aria-label={t("slash.title")}>
          {#each suggested as entry (entry.name)}
            <li><button type="button" class="link" onclick={() => ((draft = "/" + entry.name + (entry.arg || entry.project ? " " : "")), box?.focus())}>/{entry.name}{entry.arg ? " " + entry.arg : ""}</button>
              <span class="muted">{entry.project ? projectCommands.find((command) => command.name === entry.name)?.description || t("slash.project") : t(("slash.d." + entry.name) as MessageKey)}</span></li>
          {/each}
        </ul>
      {/if}
      {#if showHelp}
        <div class="slash help" role="region" aria-label={t("slash.title")}>
          <p><strong>{t("slash.title")}</strong> <button type="button" class="link" onclick={() => (showHelp = false)}>{t("chat.cancel")}</button></p>
          <ul>{#each COMMANDS as command (command.name)}<li><code>/{command.name}{command.arg ? " " + command.arg : ""}</code> {t(("slash.d." + command.name) as MessageKey)}</li>{/each}</ul>
          {#if projectCommands.length}<p>{t("slash.project_list")}</p><ul>{#each projectCommands as command (command.name)}<li><code>/{command.name}</code> {command.description}</li>{/each}</ul>{/if}
        </div>
      {/if}
      {#if commandNotice}<p class="command-notice" role="status">{commandNotice}</p>{/if}
      {#if queue.length}
        <ul class="queue" aria-label={t("queue.title")}>
          {#each queue as waiting, index (index)}
            <li><span>{t("queue.waiting")} {waiting}</span><button type="button" class="link" onclick={() => (queue = queue.filter((_, other) => other !== index))}>{t("queue.remove")}<span class="visually-hidden"> {waiting}</span></button></li>
          {/each}
        </ul>
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
      <!-- As LM Studio does: the room taken in the context and the speed stay under the field once the answer is written (those of the last answer of this
           conversation), not only while it is written. The keys are said while nothing is known yet. -->
      <p class="meter" id="keys">
        {#if meterContext}
          {#if meterContext.total > 0}<progress class="context-gauge" max={meterContext.total} value={Math.min(meterContext.used, meterContext.total)} aria-hidden="true"></progress>{/if}
          {t("chat.tokens", meterContext.used, meterContext.total)}{meterContext.total > 0 ? " (" + Math.round((100 * meterContext.used) / meterContext.total) + " %)" : ""}{meterSpeed
            ? " · " + t("chat.speed", meterSpeed)
            : ""}
        {:else if meterSpeed}{t("chat.speed", meterSpeed)}{:else}{t("chat.keys")}{/if}
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
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
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

  .memory {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-1) var(--space-2);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-pill);
    font-size: var(--text-sm);
    color: var(--color-text-muted);
    white-space: nowrap;
  }

  .memory .dot {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: transparent;
    box-shadow: inset 0 0 0 2px var(--color-text-muted); /* an empty ring: nothing in memory */
  }

  .memory.loaded {
    border-color: var(--color-accent);
    color: var(--color-accent-text);
  }

  .memory.loaded .dot {
    background: var(--color-accent); /* a full dot: loaded. The words say it too, the colour is not alone */
    box-shadow: none;
  }

  .memory.loading {
    border-color: var(--color-accent);
  }

  .memory.loading .dot {
    box-shadow: inset 0 0 0 2px var(--color-accent);
    background: conic-gradient(var(--color-accent) 0 30%, transparent 30% 100%); /* a quarter filled that turns: on its way into memory */
    animation: memory-loading 1.2s linear infinite;
  }

  @keyframes memory-loading {
    to {
      transform: rotate(1turn);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .memory.loading .dot {
      animation: none;
    }
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

  .thread-area {
    position: relative;
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
  }

  .scroll {
    flex: 1;
    min-height: 0;
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
    overflow-y: auto;
    scrollbar-width: thin;
  }

  /* On the side of the thread, not in the middle of the text it covers (maintainer, 2026-11-21); on a phone too, at thumb's reach above the field.
     Not glued to the edge either (maintainer, 2026-11-22): on a wide screen it stands just right of the column of text, otherwise a comfortable margin in. */
  .to-bottom {
    position: absolute;
    right: max(var(--space-5), calc((100% - var(--measure)) / 2 - 3.5rem));
    bottom: var(--space-5);
    display: grid;
    place-items: center;
    width: 2.75rem;
    height: 2.75rem;
    padding: 0;
    border: 1px solid var(--color-accent); /* an older browser without color-mix keeps these */
    border: 1px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
    border-radius: 50%;
    background: var(--color-surface-raised);
    background: color-mix(in srgb, var(--color-surface-raised) 88%, transparent);
    backdrop-filter: blur(6px);
    color: var(--color-accent-text);
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.25), 0 1px 3px rgb(0 0 0 / 0.2);
    cursor: pointer;
    transition: background 0.15s, color 0.15s, transform 0.15s, box-shadow 0.15s;
  }

  @media (max-width: 40rem) {
    .to-bottom {
      right: var(--space-4);
      bottom: var(--space-4);
    }
  }

  .to-bottom:hover {
    background: var(--color-accent);
    color: var(--color-on-accent);
    transform: translateY(-1px);
    box-shadow: 0 8px 22px rgb(0 0 0 / 0.3), 0 1px 3px rgb(0 0 0 / 0.2);
  }

  .to-bottom:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 3px;
  }

  @media (prefers-reduced-motion: reduce) {
    .to-bottom,
    .to-bottom:hover {
      transition: none;
      transform: none;
    }
  }

  .to-bottom.writing {
    box-shadow: 0 0 0 3px var(--color-accent-soft), 0 0 0 4px var(--color-accent), 0 4px 14px rgb(0 0 0 / 0.35); /* a ring: the answer is still being written */
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
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
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
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
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
    font-variant-numeric: tabular-nums;
  }

  .context-gauge {
    width: 4rem;
    height: 0.35rem;
    margin-right: var(--space-2);
    vertical-align: middle;
    accent-color: var(--color-accent);
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

  .mission-banner {
    margin: 0;
    padding: var(--space-2) var(--space-4);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }

  .slash,
  .queue {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    list-style: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--text-sm);
    max-height: 14rem;
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
    overflow-y: auto;
  }

  .slash li,
  .queue li {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: baseline;
    overflow-wrap: anywhere;
  }

  .slash.help ul {
    padding-left: var(--space-4);
    list-style: disc;
  }

  .slash .muted {
    color: var(--color-text-muted);
  }

  .command-notice {
    margin: 0;
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }

  .verify ul {
    margin: 0;
    padding-left: var(--space-4);
    max-height: 16rem;
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
    overflow-y: auto;
    overflow-wrap: anywhere;
  }
</style>
