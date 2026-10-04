import { useEffect, useRef } from "react";

/** Calls `fn` once the value stopped changing for `ms`; sliders fire on every step. */
export function useDebounced<T>(fn: (v: T) => void, ms = 300): (v: T) => void {
  const timer = useRef<number | null>(null);
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  return (v: T) => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => latest.current(v), ms);
  };
}
