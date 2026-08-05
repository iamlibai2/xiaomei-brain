import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import type { ChatArtifactReference } from "../../types";

export interface ArtifactMentionMenuHandle {
  handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): boolean;
}

interface ArtifactMentionMenuProps {
  agentId: string;
  query: string;
  onSelect: (reference: ChatArtifactReference) => void;
  onClose: () => void;
}

interface ArtifactOption {
  id: string;
  sessionId: string;
  name: string;
  mimeType: string;
  size: number;
  kind: "image" | "audio" | "video" | "text" | "document" | "file";
  description: string;
  displayPath: string;
  updatedAt: number;
}

const ALLOWED_KINDS = new Set<ArtifactOption["kind"]>([
  "image", "audio", "video", "text", "document", "file",
]);

function optionFrom(value: unknown): ArtifactOption | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (
    typeof item.id !== "string"
    || typeof item.session_id !== "string"
    || typeof item.name !== "string"
  ) return null;
  const rawKind = String(item.kind || "file") as ArtifactOption["kind"];
  return {
    id: item.id,
    sessionId: item.session_id,
    name: item.name,
    mimeType: typeof item.mime_type === "string" ? item.mime_type : "application/octet-stream",
    size: typeof item.size === "number" ? item.size : 0,
    kind: ALLOWED_KINDS.has(rawKind) ? rawKind : "file",
    description: typeof item.description === "string" ? item.description : "",
    displayPath: typeof item.display_path === "string" ? item.display_path : "",
    updatedAt: typeof item.updated_at === "number"
      ? item.updated_at
      : typeof item.created_at === "number" ? item.created_at : 0,
  };
}

function normalized(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function extensionLabel(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1).slice(0, 4).toUpperCase() : "FILE";
}

function formatSize(size: number): string {
  if (size <= 0) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function usefulDescription(value: string): string {
  const description = value.trim();
  return /^(created|updated) by\s+/i.test(description) ? "" : description;
}

export const ArtifactMentionMenu = forwardRef<
  ArtifactMentionMenuHandle,
  ArtifactMentionMenuProps
>(function ArtifactMentionMenu({ agentId, query, onSelect, onClose }, ref) {
  const { t } = useTranslation();
  const [artifacts, setArtifacts] = useState<ArtifactOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void window.gateway.listArtifacts({ agentId, limit: 100, offset: 0 }).then((response) => {
      if (!active) return;
      if (response.error) throw new Error(response.error.message);
      const rows = Array.isArray(response.result?.artifacts) ? response.result.artifacts : [];
      setArtifacts(rows
        .map(optionFrom)
        .filter((item): item is ArtifactOption => item !== null)
        .sort((left, right) => right.updatedAt - left.updatedAt));
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [agentId]);

  const matches = useMemo(() => {
    const needle = normalized(query);
    return artifacts.filter((artifact) => (
      !needle
      || normalized(artifact.name).includes(needle)
      || normalized(artifact.description).includes(needle)
      || normalized(artifact.displayPath).includes(needle)
      || normalized(artifact.mimeType).includes(needle)
    )).slice(0, 20);
  }, [artifacts, query]);

  useEffect(() => setActiveIndex(0), [query]);

  const select = (artifact: ArtifactOption) => onSelect({
    artifactId: artifact.id,
    sessionId: artifact.sessionId,
    name: artifact.name,
    mimeType: artifact.mimeType,
    size: artifact.size,
    kind: artifact.kind,
    description: artifact.description,
  });

  useImperativeHandle(ref, () => ({
    handleKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
        event.preventDefault();
        return true;
      }
      if (!matches.length) return false;
      if (event.key === "ArrowDown") {
        setActiveIndex((value) => (value + 1) % matches.length);
        event.preventDefault();
        return true;
      }
      if (event.key === "ArrowUp") {
        setActiveIndex((value) => (value - 1 + matches.length) % matches.length);
        event.preventDefault();
        return true;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        if (matches[activeIndex]) select(matches[activeIndex]);
        event.preventDefault();
        return true;
      }
      return false;
    },
  }), [activeIndex, matches, onClose]);

  if (loading) {
    return <div className="artifact-mention-menu is-message">{t("mentionUi.loading")}</div>;
  }
  if (error) {
    return <div className="artifact-mention-menu is-message">{t("mentionUi.error")}</div>;
  }
  if (!matches.length) {
    return <div className="artifact-mention-menu is-message">{t("mentionUi.empty")}</div>;
  }

  return (
    <div className="artifact-mention-menu" role="listbox" aria-label={t("mentionUi.choose")}>
      <div className="artifact-mention-heading">{t("mentionUi.recent")}</div>
      {matches.map((artifact, index) => (
        <button
          type="button"
          key={`${artifact.sessionId}:${artifact.id}`}
          className={`artifact-mention-item ${activeIndex === index ? "is-active" : ""}`}
          onMouseEnter={() => setActiveIndex(index)}
          onClick={() => select(artifact)}
        >
          <span className="artifact-mention-file-type">{extensionLabel(artifact.name)}</span>
          <span className="artifact-mention-copy">
            <strong>{artifact.name}</strong>
            <small>{usefulDescription(artifact.description) || artifact.displayPath || t("mentionUi.file")}</small>
          </span>
          <span className="artifact-mention-size">{formatSize(artifact.size)}</span>
        </button>
      ))}
    </div>
  );
});
