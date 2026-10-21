import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Accent = "cyan" | "violet" | "amber";
export type Density = "comfortable" | "compact";

export interface NicheScopeSettings {
  productName: string;
  tagline: string;
  displayName: string;
  loginId: string;
  password: string;
  accent: Accent;
  density: Density;
}

const defaults: NicheScopeSettings = {
  productName: "NicheScope",
  tagline: "Amazon Product Research and Market Intelligence",
  displayName: "Arjun Shah",
  loginId: "admin",
  password: "nichescope",
  accent: "cyan",
  density: "comfortable",
};

const STORAGE_KEY = "nichescope-settings";

function readSettings(): NicheScopeSettings {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved ? { ...defaults, ...JSON.parse(saved) } : defaults;
  } catch {
    return defaults;
  }
}

const SettingsContext = createContext<{
  settings: NicheScopeSettings;
  updateSettings: (patch: Partial<NicheScopeSettings>) => void;
  resetSettings: () => void;
}>({ settings: defaults, updateSettings: () => undefined, resetSettings: () => undefined });

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<NicheScopeSettings>(readSettings);
  useEffect(() => {
    document.documentElement.dataset.accent = settings.accent;
    document.documentElement.dataset.density = settings.density;
  }, [settings.accent, settings.density]);
  const value = useMemo(() => ({
    settings,
    updateSettings: (patch: Partial<NicheScopeSettings>) => setSettings((current) => {
      const next = { ...current, ...patch };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    }),
    resetSettings: () => {
      window.localStorage.removeItem(STORAGE_KEY);
      setSettings(defaults);
    },
  }), [settings]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  return useContext(SettingsContext);
}

export { defaults as defaultNicheScopeSettings };
