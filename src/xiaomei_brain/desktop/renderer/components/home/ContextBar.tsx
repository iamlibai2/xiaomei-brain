import { useTranslation } from "react-i18next";
import { Icon } from "../ui";

export function ContextBar() {
  const { t } = useTranslation();
  return (
    <div className="context-bar">
      <button className="context-bar-item">
        <Icon name="map-pin" size={14} />
        <span>{t("home.workspace")}</span>
        <span>▾</span>
      </button>
      <button className="context-bar-item">
        <Icon name="shield" size={14} />
        <span>{t("home.defaultPermission")}</span>
        <span>▾</span>
      </button>
    </div>
  );
}
