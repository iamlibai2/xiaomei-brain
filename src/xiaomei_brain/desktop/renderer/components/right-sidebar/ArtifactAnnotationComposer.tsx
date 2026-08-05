import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const COMPOSER_WIDTH = 360;
const COMPOSER_HEIGHT_ESTIMATE = 218;
const VIEWPORT_MARGIN = 12;
const ANCHOR_GAP = 10;

export function ArtifactAnnotationComposer({
  excerpt,
  location,
  placeholder,
  getAnchorRect,
  onCancel,
  onSubmit,
}: {
  excerpt: string;
  location: string;
  placeholder: string;
  getAnchorRect: () => DOMRect | null;
  onCancel: () => void;
  onSubmit: (instruction: string) => void;
}) {
  const { t } = useTranslation();
  const [instruction, setInstruction] = useState("");
  const [position, setPosition] = useState({ left: VIEWPORT_MARGIN, top: VIEWPORT_MARGIN });

  useEffect(() => {
    let frame = 0;
    const updatePosition = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const rect = getAnchorRect();
        if (!rect) return;
        const width = Math.min(COMPOSER_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2);
        const roomOnRight = window.innerWidth - rect.right - ANCHOR_GAP;
        const left = roomOnRight >= width
          ? rect.right + ANCHOR_GAP
          : Math.max(VIEWPORT_MARGIN, Math.min(rect.left, window.innerWidth - width - VIEWPORT_MARGIN));
        const roomBelow = window.innerHeight - rect.bottom - ANCHOR_GAP;
        const top = roomBelow >= COMPOSER_HEIGHT_ESTIMATE
          ? rect.bottom + ANCHOR_GAP
          : Math.max(VIEWPORT_MARGIN, rect.top - COMPOSER_HEIGHT_ESTIMATE - ANCHOR_GAP);
        setPosition({ left, top });
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [getAnchorRect]);

  const submit = () => {
    const value = instruction.trim();
    if (!value) return;
    onSubmit(value);
  };

  return (
    <div className="artifact-annotation-composer" style={position}>
      <blockquote>{excerpt}</blockquote>
      <textarea
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        placeholder={placeholder}
        rows={3}
        autoFocus
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onCancel();
          }
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <div>
        <small>{location}</small>
        <button type="button" onClick={onCancel}>{t("artifactUi.cancel")}</button>
        <button type="button" className="primary" onClick={submit} disabled={!instruction.trim()}>
          {t("artifactUi.edit")}
        </button>
      </div>
    </div>
  );
}
