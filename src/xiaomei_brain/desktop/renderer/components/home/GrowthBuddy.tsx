import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui";

interface GrowthBuddyProps {
  title?: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
}

export function GrowthBuddy({
  title,
  description,
  actionText,
  onAction,
}: GrowthBuddyProps) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  const displayTitle = title ?? t("home.activityNotice");
  const displayDesc = description ?? t("home.activityContent");
  const displayAction = actionText ?? t("home.activityAction");

  return (
    <div className="growth-buddy">
      <div className="growth-buddy-bubble">
        <Button
          variant="ghost"
          size="icon-sm"
          icon="x"
          className="growth-buddy-close"
          onClick={() => setVisible(false)}
          title={t("sidebar.close")}
        />
        <div className="growth-buddy-title">{displayTitle}</div>
        <div className="growth-buddy-desc">{displayDesc}</div>
        <Button variant="primary" size="sm" className="growth-buddy-action" onClick={onAction}>
          {displayAction}
        </Button>
      </div>
      <div className="growth-buddy-avatar">🐱</div>
    </div>
  );
}
