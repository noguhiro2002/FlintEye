import { useEffect, useRef, useState } from "react";

type LoadThumbnail = (signal: AbortSignal) => Promise<void>;
type EnqueueThumbnail = (load: LoadThumbnail) => () => void;

export function createRecordingThumbnailQueue(): EnqueueThumbnail {
  const pending = new Set<() => void>();
  let active = 0;

  function startNext() {
    const next = pending.values().next().value;
    // Leave connections available for playback and other API requests.
    if (!next || active >= 2) return;
    pending.delete(next);
    active += 1;
    next();
  }

  return load => {
    const controller = new AbortController();
    const start = () => {
      void load(controller.signal).finally(() => {
        active -= 1;
        startNext();
      });
    };
    pending.add(start);
    startNext();
    return () => {
      pending.delete(start);
      controller.abort();
    };
  };
}

interface RecordingThumbnailProps {
  fileId: string;
  url: string;
  alt: string;
  paused: boolean;
  enqueue: EnqueueThumbnail;
  onError: (fileId: string) => void;
}

export function RecordingThumbnail({ fileId, url, alt, paused, enqueue, onError }: RecordingThumbnailProps): JSX.Element {
  const placeholder = useRef<HTMLSpanElement>(null);
  const objectUrl = useRef("");
  const [visible, setVisible] = useState(false);
  const [source, setSource] = useState("");

  useEffect(() => {
    const target = placeholder.current;
    if (!target) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: "180px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  useEffect(() => {
    if (!visible || source || paused) return;
    return enqueue(async signal => {
      try {
        const response = await fetch(url, { credentials: "include", signal });
        if (!response.ok) throw new Error("Recording thumbnail unavailable");
        const blob = await response.blob();
        if (signal.aborted) return;
        objectUrl.current = URL.createObjectURL(blob);
        setSource(objectUrl.current);
      } catch {
        if (!signal.aborted) onError(fileId);
      }
    });
  }, [enqueue, fileId, onError, paused, source, url, visible]);

  return source
    ? <img src={source} alt={alt} onError={() => onError(fileId)} />
    : <span className="recording-thumbnail-placeholder" ref={placeholder} />;
}
