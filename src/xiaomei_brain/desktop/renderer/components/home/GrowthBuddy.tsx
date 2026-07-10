import { useState } from "react";

interface GrowthBuddyProps {
  title?: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
}

export function GrowthBuddy({
  title = "活动通知",
  description = "xiaomei-brain 新版本发布，快来体验记忆系统升级",
  actionText = "立即体验",
  onAction,
}: GrowthBuddyProps) {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  return (
    <div className="growth-buddy">
      <div className="growth-buddy-bubble">
        <button
          className="growth-buddy-close"
          onClick={() => setVisible(false)}
        >
          ✕
        </button>
        <div className="growth-buddy-title">{title}</div>
        <div className="growth-buddy-desc">{description}</div>
        <button className="growth-buddy-action" onClick={onAction}>
          {actionText}
        </button>
      </div>
      <div className="growth-buddy-avatar">🐱</div>
    </div>
  );
}
