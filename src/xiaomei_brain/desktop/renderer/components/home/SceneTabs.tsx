import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export type HomeMode = "working" | "coding" | "design";

interface SceneTabsProps {
  selected: HomeMode;
  onSelect: (mode: HomeMode) => void;
}

const TAB_KEYS: { mode: HomeMode; key: string }[] = [
  { mode: "working", key: "home.sceneWork" },
  { mode: "coding", key: "home.sceneCoding" },
  { mode: "design", key: "home.sceneDesign" },
];

export function SceneTabs({ selected, onSelect }: SceneTabsProps) {
  const { t } = useTranslation();
  const tabs = useMemo(
    () => TAB_KEYS.map((tab) => ({ ...tab, label: t(tab.key) })),
    [t]
  );
  return (
    <div className="scene-tabs">
      {tabs.map((tab) => (
        <button
          key={tab.mode}
          className={`scene-tab ${selected === tab.mode ? "selected" : ""}`}
          onClick={() => onSelect(tab.mode)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
