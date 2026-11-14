<script lang="ts">
  // An area that has not moved to the new interface yet: said plainly, with the way to the present one.
  import { t } from "../lib/messages";

  let { name }: { name: string } = $props();
</script>

<section>
  <h1>{t("soon.title", name)}</h1>
  <p>{t("soon.body")}</p>
  <p><a href="/">{t("soon.open")}</a></p>
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    max-width: var(--measure);
    padding: var(--space-6) var(--space-5);
  }

  h1 {
    font-size: var(--text-lg);
  }

  p {
    color: var(--color-text-muted);
  }
</style>
