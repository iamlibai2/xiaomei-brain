export type HomeMode = "working" | "coding" | "design";

interface SceneTabsProps {
  selected: HomeMode;
  onSelect: (mode: HomeMode) => void;
}

const TABS: { mode: HomeMode; label: string }[] = [
  { mode: "working", label: "日常办公" },
  { mode: "coding", label: "@代码开发" },
  { mode: "design", label: "@设计创意" },
];

export function SceneTabs({ selected, onSelect }: SceneTabsProps) {
  return (
    <div className="scene-tabs">
      {TABS.map((tab) => (
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
