import {
  createContext, useCallback, useContext, useEffect, useState,
} from "react";

// Holds the active color theme ("light" | "dark") and exposes a toggle. An explicit choice persists
// in localStorage so a refresh keeps it; before the user ever picks, we follow the OS preference
// (prefers-color-scheme) and keep tracking it live until the first manual toggle. The matching class
// is applied to <html> — see styles.css (html.theme-light) and the anti-flash script in index.html.
// localStorage is written ONLY on an explicit choice, so "has the user picked?" stays detectable.
const ThemeContext = createContext(null);

const STORAGE_KEY = "theme";

function getInitialTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(getInitialTheme);

  // Reflect the theme onto <html> (the anti-flash script set it pre-mount; this keeps it in sync).
  useEffect(() => {
    document.documentElement.classList.toggle("theme-light", theme === "light");
  }, [theme]);

  const setTheme = useCallback((t) => {
    localStorage.setItem(STORAGE_KEY, t);
    setThemeState(t);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "light" ? "dark" : "light";
      localStorage.setItem(STORAGE_KEY, next);
      return next;
    });
  }, []);

  // Until the user makes an explicit choice, follow OS preference changes live.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e) => {
      if (localStorage.getItem(STORAGE_KEY)) return;
      setThemeState(e.matches ? "light" : "dark");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const value = { theme, toggleTheme, setTheme };
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
