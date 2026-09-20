"use client";

import { useEffect, useId, useRef, useState } from "react";
import styles from "./Menu.module.css";

export type MenuAction = {
  key: string;
  label: string;
  onSelect: () => void;
};

/** Minimal accessible dropdown menu -- closes on outside click, Escape,
 * and item selection; each item is keyboard-reachable (native <button>). */
export function Menu({ trigger, items }: { trigger: React.ReactNode; items: MenuAction[] }) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className={styles.wrapper} ref={wrapperRef}>
      <button
        type="button"
        className={styles.trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((value) => !value)}
      >
        {trigger}
      </button>
      {open ? (
        <div id={menuId} role="menu" className={styles.panel}>
          {items.map((item) => (
            <button
              key={item.key}
              role="menuitem"
              type="button"
              className={styles.item}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
