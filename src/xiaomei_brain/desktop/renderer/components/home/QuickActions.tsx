import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Icon, type IconName } from "../ui";

interface QuickActionDef {
  id: string;
  key: string;
  icon: IconName;
}

interface QuickActionsProps {
  onAction: (id: string) => void;
}

const ACTIONS: QuickActionDef[] = [
  { id: "doc", key: "home.quickDocProcessing", icon: "file-text" },
  { id: "finance", key: "home.quickFinance", icon: "currency-dollar" },
  { id: "data", key: "home.quickDataAnalysis", icon: "chart-bar" },
  { id: "more", key: "home.quickMore", icon: "dots-vertical" },
];

export function QuickActions({ onAction }: QuickActionsProps) {
  const { t } = useTranslation();
  const actions = useMemo(
    () => ACTIONS.map((a) => ({ ...a, label: t(a.key) })),
    [t]
  );
  return (
    <div className="wb-home-composer__chips">
      {actions.map((action) => (
        <button
          key={action.id}
          className="quick-action-chip"
          onClick={() => onAction(action.id)}
        >
          <Icon name={action.icon} size={14} />
          <span>{action.label}</span>
        </button>
      ))}
    </div>
  );
}
