"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

/**
 * Segmented dark/light theme toggle. Reads + writes localStorage.theme and
 * flips data-theme on <html>. The pre-paint init script in layout.tsx
 * applies the stored value on initial load — this component just renders
 * the current state and lets the user change it.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    // Read whatever the pre-paint script applied.
    const current = document.documentElement.getAttribute("data-theme");
    if (current === "light" || current === "dark") {
      setTheme(current);
    }
  }, []);

  function pick(next: "dark" | "light") {
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("theme", next);
    } catch {
      // localStorage blocked — preference stays for this tab only.
    }
  }

  return (
    <div
      role="group"
      aria-label="Color theme"
      style={{
        display: "inline-flex",
        gap: 0,
        padding: 3,
        background: "var(--bg-elev-1)",
        border: "1px solid var(--line)",
        borderRadius: 8,
        width: "100%",
      }}
    >
      <ToggleButton active={theme === "dark"} onClick={() => pick("dark")} label="Dark">
        <Moon size={13} strokeWidth={2} />
      </ToggleButton>
      <ToggleButton active={theme === "light"} onClick={() => pick("light")} label="Light">
        <Sun size={13} strokeWidth={2} />
      </ToggleButton>
    </div>
  );
}

function ToggleButton({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="theme-toggle-btn"
      style={{
        flex: 1,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        height: 30,
        padding: "0 10px",
        background: active ? "var(--bg-elev-2)" : "transparent",
        color: active ? "var(--fg)" : "var(--fg-muted)",
        border: 0,
        borderRadius: 6,
        font: "inherit",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        transition: "background 120ms ease, color 120ms ease",
      }}
    >
      {children}
      {label}
    </button>
  );
}
