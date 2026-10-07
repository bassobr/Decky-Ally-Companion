import { useEffect, useRef } from "react";

/** Calls `fn` once the value stopped changing for `ms`; sliders fire on every step. A value still
 * waiting when the component goes away (the panel closes) is sent right then, not dropped. */
export function useDebounced<T>(fn: (v: T) => void, ms = 300): (v: T) => void {
  const timer = useRef<number | null>(null);
  const pending = useRef<{ v: T } | null>(null);
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
    if (pending.current) latest.current(pending.current.v);
  }, []);
  return (v: T) => {
    if (timer.current) window.clearTimeout(timer.current);
    pending.current = { v };
    timer.current = window.setTimeout(() => {
      pending.current = null;
      latest.current(v);
    }, ms);
  };
}
