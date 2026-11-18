// Copying a text: the clipboard API, or, on an address that is not secure (a phone on the local network) where that API is absent, a hidden
// text area and the old copy command.
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}
