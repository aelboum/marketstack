"use client";

// Minimal locale switch (dashboard-design integration, approved scope:
// header language toggle + Navigation + Dashboard page text only -- see
// the mockup's own NL/EN toggle in design/dashboard-design-mockup/).
// This is deliberately NOT a general i18n framework: there is no message
// catalog, no pluralization engine, no per-page translation coverage.
// Every other page in the product stays Dutch-only regardless of this
// toggle's state -- only components that explicitly call `useLocale()`
// change language. Persisted client-side only (no server dependency),
// defaults to Dutch (the product's existing convention).
import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "NL" | "EN";

const STORAGE_KEY = "product.locale";

type LocaleState = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
};

const LocaleContext = createContext<LocaleState | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>("NL");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "NL" || stored === "EN") setLocale(stored);
    } catch {
      // Private browsing / storage disabled -- default (NL) stands.
    }
  }, []);

  const value = useMemo<LocaleState>(
    () => ({
      locale,
      setLocale: (next) => {
        setLocale(next);
        try {
          window.localStorage.setItem(STORAGE_KEY, next);
        } catch {
          // Nothing to persist to -- the in-memory value still applies
          // for the rest of this session.
        }
      },
    }),
    [locale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleState {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocale() must be called inside a <LocaleProvider>.");
  }
  return context;
}

/** `t("Dutch text", "English text")` -- picks the current locale's
 * string. Named for brevity at every call site, matching the mockup's
 * own `L(en, du)` helper in spirit (argument order flipped: Dutch first,
 * since this product's default and primary language is Dutch). */
export function useTranslate(): (nl: string, en: string) => string {
  const { locale } = useLocale();
  return (nl: string, en: string) => (locale === "EN" ? en : nl);
}
