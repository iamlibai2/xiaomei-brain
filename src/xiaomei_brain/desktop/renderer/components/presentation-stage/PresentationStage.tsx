import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Icon } from "../ui";
import "./presentation-stage.css";

export type PresentationStageLayout = "single" | "split" | "gallery" | "media_with_details";

export function PresentationStage({
  title,
  layout,
  itemCount,
  activeIndex,
  onClose,
  onPrevious,
  onNext,
  children,
}: {
  title: string;
  layout: PresentationStageLayout;
  itemCount: number;
  activeIndex: number;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();

  useEffect(() => {
    void window.win.setFullScreen(true);
    return () => { void window.win.setFullScreen(false); };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowLeft") onPrevious?.();
      else if (event.key === "ArrowRight") onNext?.();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, onNext, onPrevious]);

  return createPortal(
    <section className={`presentation-stage layout-${layout}`} role="dialog" aria-modal="true" aria-label={title}>
      <div className="presentation-stage-canvas">{children}</div>
      <div className="presentation-stage-chrome presentation-stage-title" title={title}>{title}</div>
      {itemCount > 1 && layout === "single" && (
        <div className="presentation-stage-chrome presentation-stage-pagination">
          <button type="button" onClick={onPrevious} aria-label={t("stageUi.previous")}>
            <Icon name="chevron-left" size={17} />
          </button>
          <span>{activeIndex + 1} / {itemCount}</span>
          <button type="button" onClick={onNext} aria-label={t("stageUi.next")}>
            <Icon name="chevron-right" size={17} />
          </button>
        </div>
      )}
      <button
        type="button"
        className="presentation-stage-chrome presentation-stage-exit"
        onClick={onClose}
        title={t("visualize.exitFullscreen")}
        aria-label={t("visualize.exitFullscreen")}
      >
        <Icon name="minimize" size={17} />
      </button>
    </section>,
    document.body,
  );
}
