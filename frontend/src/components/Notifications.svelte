<script lang="ts">
  // The notification channels: where Lutin sends a message when a scheduled task is done (Gotify, ntfy, Telegram, a webhook). The form is drawn from what the
  // server says each kind asks for. A secret (token, webhook address) is typed once and never shown again: the list only says that it is set.
  // Adding, testing and removing are for the machine itself (the server refuses a paired device and says so).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Field = { key: string; label: string; required: boolean; secret: boolean };
  type Kind = { id: string; name: string; fields: Field[] };
  type Channel = { id: string; name: string; type: string; type_name: string; params: Record<string, string>; secrets_set: string[] };
  type View = { types: Kind[]; channels: Channel[] };

  let view = $state<View | null>(null);
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);
  let removing = $state("");
  let name = $state("");
  let kind = $state("");
  let values = $state<Record<string, string>>({});

  const fields = $derived(view?.types.find((item) => item.id === kind)?.fields ?? []);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("notifications.only_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      done = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  function show(next: View): void {
    view = next;
    if (!kind) kind = next.types[0]?.id ?? "";
  }

  const load = (): Promise<void> => act(async () => show(await api<View>("GET", "/notification-channels")));

  const add = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      show(await api<View>("POST", "/notification-channels", { name: name.trim(), type: kind, params: values }));
      name = "";
      values = {};
    });
  };

  const test = (channel: Channel): Promise<void> =>
    act(async () => {
      await api("POST", `/notification-channels/${encodeURIComponent(channel.id)}/test`, {});
      done = t("notifications.test_sent", channel.name);
    });

  const remove = (channel: Channel): Promise<void> =>
    act(async () => {
      show(await api<View>("DELETE", `/notification-channels/${encodeURIComponent(channel.id)}`));
      removing = "";
    });

  onMount(() => {
    void load();
  });
</script>

<section class="notifications" aria-labelledby="notifications-title">
  <h2 id="notifications-title">{t("notifications.title")}</h2>
  <p class="muted">{t("notifications.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}

  {#if view}
    {#if view.channels.length === 0}
      <p class="muted">{t("notifications.none")}</p>
    {:else}
      <ul class="list" aria-label={t("notifications.title")}>
        {#each view.channels as channel (channel.id)}
          <li>
            <span class="what"><strong>{channel.name}</strong> <span class="muted">{channel.type_name}</span></span>
            <span class="actions">
              <button type="button" class="button" disabled={busy} onclick={() => test(channel)}>{t("notifications.test")}</button>
              {#if removing === channel.id}
                <span class="confirm" role="group" aria-label={t("notifications.remove_confirm", channel.name)}>
                  <span>{t("notifications.remove_confirm", channel.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(channel)}>{t("notifications.remove_yes")}</button>
                  <button type="button" class="button" onclick={() => (removing = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (removing = channel.id)}>{t("notifications.remove")}</button>
              {/if}
            </span>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={add}>
      <h3>{t("notifications.add_title")}</h3>
      <label for="notification-name">{t("notifications.name")}</label>
      <input id="notification-name" type="text" bind:value={name} maxlength="40" autocomplete="off" required />
      <label for="notification-kind">{t("notifications.kind")}</label>
      <select id="notification-kind" bind:value={kind} onchange={() => (values = {})}>
        {#each view.types as item (item.id)}<option value={item.id}>{item.name}</option>{/each}
      </select>
      {#each fields as field (kind + field.key)}
        <label for={"notification-" + field.key}>{field.label}</label>
        <input id={"notification-" + field.key} type={field.secret ? "password" : "text"} bind:value={values[field.key]} autocomplete="off" spellcheck="false" required={field.required} />
      {/each}
      <div class="actions"><button type="submit" class="button primary" disabled={busy || !name.trim()}>{t("notifications.add")}</button></div>
    </form>
  {:else if !problem}
    <p class="muted">{t("notifications.loading")}</p>
  {/if}
</section>

<style>
  .notifications {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
  }

  h3 {
    font-size: var(--text-md);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .list li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }

  .what {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .confirm,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  label {
    font-weight: 600;
  }

  input,
  select {
    max-width: 24rem;
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

  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .done {
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }
</style>
