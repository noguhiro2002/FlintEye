import { useEffect, useRef } from "react";

export function usePolling(fn: () => void | Promise<void>, intervalMs: number): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    const run = () => {
      void fnRef.current();
    };
    run();
    const id = window.setInterval(run, intervalMs);
    return () => {
      window.clearInterval(id);
    };
  }, [intervalMs]);
}
