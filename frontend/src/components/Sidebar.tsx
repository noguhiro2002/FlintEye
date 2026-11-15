type PageKey = "dashboard" | "information" | "settings" | "live" | "multiview" | "recordings";

interface SidebarProps {
  active: PageKey;
  onSelect: (page: PageKey) => void;
  brandTitle: string;
  canAccessSettings: boolean;
}

const BASE_NAV_ITEMS: Array<{ key: PageKey; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "information", label: "Information" },
  { key: "settings", label: "Settings" },
  { key: "live", label: "Live View" },
  { key: "multiview", label: "Multiview" },
  { key: "recordings", label: "Recordings" },
];

export function Sidebar({ active, onSelect, brandTitle, canAccessSettings }: SidebarProps): JSX.Element {
  const navItems = BASE_NAV_ITEMS.filter((item) => canAccessSettings || item.key !== "settings");
  return (
    <aside className="sidebar">
      <div className="brand">{brandTitle}</div>
      <nav className="nav">
        {navItems.map((item) => (
          <button
            type="button"
            key={item.key}
            data-tour-nav={item.key}
            className={active === item.key ? "nav-item active" : "nav-item"}
            aria-current={active === item.key ? "page" : undefined}
            onClick={() => onSelect(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

export type { PageKey };
