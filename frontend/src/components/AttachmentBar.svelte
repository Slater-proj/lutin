<script lang="ts">
  // The button to attach a file, and what is attached to the next message: a small picture for an image, an icon and the name for a document.
  import { imageUrl } from "../lib/place";
  import Icon from "./Icon.svelte";
  import type { Attachment } from "../lib/attachments";
  import { t } from "../lib/messages";

  let { attachments, onadd, onremove, disabled = false, machine = "" }: { attachments: Attachment[]; onadd: (files: File[]) => void; onremove: (key: string) => void; disabled?: boolean; machine?: string } = $props();
  let input = $state<HTMLInputElement | null>(null);

  function chosen(event: Event): void {
    const field = event.currentTarget as HTMLInputElement;
    onadd(Array.from(field.files ?? []));
    field.value = ""; // choosing the same file again must still fire a change
  }
</script>

<input id="file-input" class="visually-hidden" type="file" multiple tabindex="-1" aria-hidden="true" bind:this={input} onchange={chosen} />
<button type="button" class="attach" {disabled} onclick={() => input?.click()}><Icon name="attach" /><span class="visually-hidden">{t("chat.attach")}</span></button>

{#if attachments.length}
  <ul class="chips" aria-label={t("chat.attached")}>
    {#each attachments as item (item.key)}
      <li class:busy={item.state === "uploading"}>
        {#if item.kind === "image" && item.state === "ready"}
          <img src={imageUrl(machine, item.id)} alt="" width="28" height="28" />
        {:else}
          <Icon name="file" size={18} />
        {/if}
        <span class="name">{item.kind === "image" && item.state === "ready" ? t("chat.image") : item.name}</span>
        {#if item.state === "uploading"}<span class="state">{t("chat.attach_uploading")}</span>{/if}
        <button type="button" class="remove" onclick={() => onremove(item.key)}><Icon name="close" size={14} /><span class="visually-hidden">{t("chat.attach_remove", item.name)}</span></button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .attach {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: var(--target);
    height: var(--target);
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--color-text-muted);
    cursor: pointer;
  }

  .attach:hover:not(:disabled) {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  .attach:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    width: 100%;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .chips li {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    max-width: 100%;
    padding: 0.2rem 0.2rem 0.2rem var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    font-size: var(--text-sm);
  }

  .chips li.busy {
    opacity: 0.7;
  }

  img {
    border-radius: var(--radius-sm);
    object-fit: cover;
  }

  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .state {
    color: var(--color-text-muted);
    font-size: var(--text-xs);
  }

  .remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.75rem;
    height: 1.75rem;
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--color-text-muted);
    cursor: pointer;
  }

  .remove:hover {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }
</style>
