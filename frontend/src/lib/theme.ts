// Light, dark, or the system's choice. The choice is kept in this browser; the colours themselves are in styles/tokens.css.
export type Theme = "system" | "light" | "dark";

const KEY = "lutin.theme";

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system"; // storage refused (private window): the system decides
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
  }
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // the theme still applies to this page
  }
}

/** Whether the page is dark right now: the choice kept here, else the system's. */
export function isDark(): boolean {
  const chosen = document.documentElement.getAttribute("data-theme");
  return chosen === "dark" || (chosen !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
}

/** Calls `change` each time the page turns dark or light, by the choice made here or by the system. Returns what stops it. */
export function watchDark(change: (dark: boolean) => void): () => void {
  const tell = (): void => change(isDark());
  const observer = new MutationObserver(tell);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  system.addEventListener("change", tell);
  return () => {
    observer.disconnect();
    system.removeEventListener("change", tell);
  };
}

export function nextTheme(theme: Theme): Theme {
  return theme === "system" ? "light" : theme === "light" ? "dark" : "system";
}
