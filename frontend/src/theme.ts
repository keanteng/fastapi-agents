export type Theme = "light" | "dark";

const STORAGE_KEY = "agents-theme";

function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark";
}

export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getStoredTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isTheme(value) ? value : null;
  } catch {
    return null;
  }
}

export function getTheme(): Theme {
  return isTheme(document.documentElement.dataset.theme ?? null)
    ? (document.documentElement.dataset.theme as Theme)
    : (getStoredTheme() ?? systemTheme());
}

function apply(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

export function setTheme(theme: Theme): void {
  apply(theme);
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage may be unavailable (private mode); the class still applies.
  }
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

export function initTheme(): Theme {
  const theme = getStoredTheme() ?? systemTheme();
  apply(theme);
  return theme;
}
