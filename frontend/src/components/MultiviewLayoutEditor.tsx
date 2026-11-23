import { useState } from "react";

interface Props {
  sources: Array<{path: string; label: string}>;
  tileCount: number;
  columns?: number | null;
  placements: (string | null)[][] | null;
  onChange: (placements: (string | null)[][] | null) => void;
}

export function MultiviewLayoutEditor({ sources, tileCount, columns, placements, onChange }: Props) {
  const [moving, setMoving] = useState<string | null>(null);
  const labels = new Map(sources.map(source => [source.path, source.label]));
  const manual = placements !== null;
  const automatic = Array.from({length: Math.ceil(sources.length / tileCount)}, (_, page) =>
    sources.slice(page * tileCount, (page + 1) * tileCount).map(source => source.path));
  const pages = manual
    ? Array.from({length: Math.max(1, placements.length, automatic.length)}, (_, page) =>
        Array.from({length: tileCount}, (_, slot) => placements[page]?.[slot] ?? null))
    : automatic;
  const unplaced = sources.filter(source => !pages.some(page => page.includes(source.path)));
  const assign = (path: string, page: number, index: number) => {
    if (!manual || !path || (!labels.has(path) && !pages.some(row => row.includes(path)))) return;
    const oldPage = pages.findIndex(row => row.includes(path));
    const oldSlot = oldPage < 0 ? -1 : pages[oldPage].indexOf(path);
    const previous = pages[page][index];
    const next = pages.map(row => [...row]);
    if (oldPage >= 0) next[oldPage][oldSlot] = previous;
    next[page][index] = path;
    onChange(next);
    setMoving(null);
  };

  if (sources.length === 0 && !manual) return null;
  return <section className="form-span-3 multiview-layout-editor" aria-label="Multiview layout preview">
    <div className="button-row">
      <strong>Camera layout</strong>
      <button type="button" onClick={() => {
        setMoving(null);
        onChange(manual ? null : automatic.map(page =>
          Array.from({length: tileCount}, (_, slot) => page[slot] ?? null)));
      }}>{manual ? "Use automatic layout" : "Arrange cameras"}</button>
    </div>
    {manual && <p className="field-help">Drag a camera to a slot, or select the camera and then select its destination.</p>}
    {unplaced.length > 0 && <div className="button-row" role="group" aria-label="Unassigned camera sources">
      {unplaced.map(({path, label}) => <button key={path} type="button" draggable
        aria-pressed={moving === path} onDragStart={event => event.dataTransfer.setData("text/plain", path)}
        onClick={() => setMoving(moving === path ? null : path)}>{label}</button>)}
    </div>}
    {pages.map((slots, page) => {
      const compact = !manual && slots.length === 2;
      const size = compact ? 2 : (columns ?? Math.ceil(Math.sqrt(tileCount)));
      const display = compact ? slots : Array.from({length: tileCount}, (_, slot) => slots[slot] ?? null);
      return <div key={page} role="group" aria-label={"View " + (page + 1)} className="multiview-layout-preview"
        style={{gridTemplateColumns: "repeat(" + size + ", minmax(0, 1fr))"}}>
        {display.map((path, slot) => {
          const label = path ? labels.get(path) ?? path : "Empty";
          const slotLabel = "Slot " + (slot + 1) + " · " + label;
          return manual ? <button key={slot} type="button" draggable={Boolean(path)}
            aria-label={slotLabel} aria-pressed={Boolean(path && moving === path)}
            onDragStart={event => { if (path) event.dataTransfer.setData("text/plain", path); }}
            onDragOver={event => event.preventDefault()}
            onDrop={event => { event.preventDefault(); assign(event.dataTransfer.getData("text/plain"), page, slot); }}
            onClick={() => { if (moving && moving !== path) assign(moving, page, slot); else setMoving(moving ? null : path); }}
          >{label}</button> : <span key={slot} aria-label={slotLabel}>{label}</span>;
        })}
      </div>;
    })}
  </section>;
}
