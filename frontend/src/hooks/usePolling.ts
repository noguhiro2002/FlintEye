import { useEffect, useRef } from "react";

export function usePolling(fn: (isCurrent: () => boolean) => void | Promise<void>, intervalMs: number): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let active = true;
    let id: number | undefined;
    const run = async () => {
      try {
        await fnRef.current(() => active);
      } finally {
        // Schedule after completion: a slow request cannot overlap the next poll.
        if (active) id = window.setTimeout(() => void run(), intervalMs);
      }
    };
    void run();
    return () => {
      active = false;
      window.clearTimeout(id);
    };
  }, [intervalMs]);
}
