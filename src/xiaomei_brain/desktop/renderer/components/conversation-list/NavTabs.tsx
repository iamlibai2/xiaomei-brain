import { Icon, type IconName } from "../ui";

interface NavItem {
  id: string;
  label: string;
  icon: IconName;
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
          <Icon name={item.icon} size={16} />
          <span className="nav-tab-label">{item.label}</span>
          {item.redDot && <span className="nav-tab-red-dot" />}
        </button>
      ))}
    </div>
  );
}

export const NavIconNames = {
  assistant: "robot" as IconName,
  project: "folder" as IconName,
  expert: "sparkles" as IconName,
  automation: "clock" as IconName,
  more: "dots-vertical" as IconName,
};
