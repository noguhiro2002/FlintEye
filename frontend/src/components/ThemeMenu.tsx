import { useLayoutEffect, useRef, useState } from "react";
import { ComputerDesktopIcon, MoonIcon, SunIcon } from "@heroicons/react/24/outline";

const THEME_KEY = "flinteye.theme";
const THEMES = [
  { value: "system", label: "Use system setting" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
] as const;
export type Theme = (typeof THEMES)[number]["value"];

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const value = localStorage.getItem(THEME_KEY);
      return value === "light" || value === "dark" ? value : "system";
    } catch {
      return "system";
    }
  });

  useLayoutEffect(() => {
    const system = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = theme === "system" ? (system.matches ? "dark" : "light") : theme;
    };
    apply();
    if (theme === "system") system.addEventListener("change", apply);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // The preference still works for this page if browser storage is unavailable.
    }
    return () => system.removeEventListener("change", apply);
  }, [theme]);

  return { theme, setTheme };
}

export function ThemeMenu({ theme, setTheme }: ReturnType<typeof useTheme>) {
  const Icon = theme === 'system' ? ComputerDesktopIcon : theme === 'dark' ? MoonIcon : SunIcon;
  const details = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const close = () => {
    if (details.current) details.current.open = false;
    trigger.current?.focus();
  };

  return <details ref={details} className="theme-menu" onKeyDown={event => {
    if (event.key === "Escape" && details.current?.open) {
      event.stopPropagation();
      close();
    }
  }}>
    <summary ref={element => { trigger.current = element; }} aria-label="Appearance" title="Appearance">
      <Icon aria-hidden="true" />
    </summary>
    <fieldset>
      <legend>Appearance</legend>
      {THEMES.map(option => <label key={option.value}>
        <input type="radio" name="appearance" value={option.value} checked={theme === option.value}
          onChange={() => setTheme(option.value)} />
        {option.label}
      </label>)}
    </fieldset>
  </details>;
}
