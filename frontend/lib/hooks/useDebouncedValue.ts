"use client";

// Debounces a fast-changing value (a search box's raw keystrokes) so
// dependent effects (an API request) only fire once typing pauses --
// UI-3 scope item 15: "preserve debouncing where appropriate ... avoid
// unnecessary API requests."
import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
