"use client";

import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";

/** The theme in use: the person's choice (data-theme on <html>), else the system's. */
function currentTheme(): Theme {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function subscribe(onChange: () => void) {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributeFilter: ["data-theme"] });
  query.addEventListener("change", onChange);
  return () => {
    observer.disconnect();
    query.removeEventListener("change", onChange);
  };
}

function choose(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("theme", theme);
  } catch {
    // Storage blocked: the choice lasts until the page is reloaded.
  }
}

export function ThemeSwitch() {
  // On the server nothing is known yet, so neither button shows as chosen.
  const theme = useSyncExternalStore<Theme | null>(subscribe, currentTheme, () => null);
  return (
    <div role="group" aria-label="Theme" className="seg border border-line bg-sunken">
      {(["light", "dark"] as const).map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={theme === option}
          onClick={() => choose(option)}
          className="seg-item flex-1 capitalize"
        >
          {option}
        </button>
      ))}
    </div>
  );
}
