import { useEffect, useId, useRef, useState } from 'react';

type DialogLabels = { heading: string; cancel: string; confirm: string };
const discardLabels: DialogLabels = {
  heading: "Discard unsaved changes?",
  cancel: "Continue editing",
  confirm: "Discard changes",
};

/** Explicit action labels for in-app navigation; tab close keeps beforeunload. */
export function useConfirmChanges() {
  const [request, setRequest] = useState<{ text: string; labels: DialogLabels }>();
  const pending = useRef<((value: boolean) => void) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  const finish = (value: boolean) => {
    dialog.current?.close();
    pending.current?.(value);
    pending.current = null;
    setRequest(undefined);
  };
  useEffect(() => { if (request) dialog.current?.showModal(); }, [request]);
  useEffect(() => () => { pending.current?.(false); }, []);
  const ask = (text: string, labels = discardLabels): Promise<boolean> => {
    // Repeated navigation while the dialog is open must not discard the draft.
    if (pending.current) return Promise.resolve(false);
    return new Promise(resolve => { pending.current = resolve; setRequest({text, labels}); });
  };
  const confirmation = <dialog ref={dialog} className="confirm-changes" aria-labelledby={id}
    onCancel={event => { event.preventDefault(); finish(false); }}>
    <h2 id={id}>{request?.labels.heading}</h2>
    <p>{request?.text}</p>
    <div className="button-row">
      <button type="button" autoFocus onClick={() => finish(false)}>{request?.labels.cancel}</button>
      <button type="button" className="button-danger" onClick={() => finish(true)}>{request?.labels.confirm}</button>
    </div>
  </dialog>;
  return { ask, confirmation };
}
