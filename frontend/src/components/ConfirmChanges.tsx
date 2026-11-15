import { useEffect, useId, useRef, useState } from 'react';

/** Explicit action labels for in-app navigation; tab close keeps beforeunload. */
export function useConfirmChanges() {
  const [message, setMessage] = useState('');
  const pending = useRef<((value: boolean) => void) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  const finish = (value: boolean) => {
    dialog.current?.close();
    pending.current?.(value);
    pending.current = null;
    setMessage('');
  };
  useEffect(() => { if (message) dialog.current?.showModal(); }, [message]);
  useEffect(() => () => { pending.current?.(false); }, []);
  const ask = (text: string): Promise<boolean> => {
    // Repeated navigation while the dialog is open must not discard the draft.
    if (pending.current) return Promise.resolve(false);
    return new Promise(resolve => { pending.current = resolve; setMessage(text); });
  };
  const confirmation = <dialog ref={dialog} className="confirm-changes" aria-labelledby={id}
    onCancel={event => { event.preventDefault(); finish(false); }}>
    <h2 id={id}>Discard unsaved changes?</h2>
    <p>{message}</p>
    <div className="button-row">
      <button type="button" autoFocus onClick={() => finish(false)}>Continue editing</button>
      <button type="button" className="button-danger" onClick={() => finish(true)}>Discard changes</button>
    </div>
  </dialog>;
  return { ask, confirmation };
}
