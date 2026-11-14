interface StatusBadgeProps {
  ok: boolean;
  label?: string;
}

export function StatusBadge({ ok, label }: StatusBadgeProps): JSX.Element {
  return (
    <span className={ok ? "status-badge ok" : "status-badge ng"}>
      {label ?? (ok ? "Healthy" : "Error")}
    </span>
  );
}
