interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  active?: boolean;
  redDot?: boolean;
}

interface NavTabsProps {
  items: NavItem[];
  onSelect: (id: string) => void;
}

export function NavTabs({ items, onSelect }: NavTabsProps) {
  return (
    <div className="nav-tabs">
      {items.map((item) => (
        <button
          key={item.id}
          className={`nav-tab ${item.active ? "active" : ""}`}
          onClick={() => onSelect(item.id)}
        >
          {item.icon}
          <span className="nav-tab-label">{item.label}</span>
          {item.redDot && <span className="nav-tab-red-dot" />}
        </button>
      ))}
    </div>
  );
}

export const NavIcons = {
  assistant: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </svg>
  ),
  project: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2H5a2 2 0 0 1-2-2" />
      <path d="M8 3v4" />
      <path d="M16 3v4" />
    </svg>
  ),
  expert: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2v6" />
      <path d="M5 8h14l-1 5a7 7 0 0 1-12 0z" />
      <path d="M12 18v4" />
    </svg>
  ),
  automation: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a10 10 0 1 0 10 10" />
      <path d="M12 6v6l4 2" />
    </svg>
  ),
  more: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </svg>
  ),
};
