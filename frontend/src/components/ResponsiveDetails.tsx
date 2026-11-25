import { useState, type ReactNode } from "react";

export function ResponsiveDetails({ summary, children }: { summary: string; children: ReactNode }) {
  const [open, setOpen] = useState(() => !window.matchMedia("(max-width: 900px)").matches);
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="responsive-details">
    <summary>{summary}</summary>
    {children}
  </details>;
}
