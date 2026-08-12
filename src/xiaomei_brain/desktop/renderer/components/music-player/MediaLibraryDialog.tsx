import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../../store";
import {
  listMediaLibrary,
  loadMediaTracks,
  MEDIA_LIBRARY_OPEN_EVENT,
  type MediaLibraryTrack,
} from "../../media-library";
import { Button, Icon } from "../ui";

function formatSize(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
export function MediaLibraryDialog() {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const [open, setOpen] = useState(false);
  const [tracks, setTracks] = useState<MediaLibraryTrack[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const receive = () => {
      setOpen(true);
      setSelected([]);
      setError("");
    };
    window.addEventListener(MEDIA_LIBRARY_OPEN_EVENT, receive);
    return () => window.removeEventListener(MEDIA_LIBRARY_OPEN_EVENT, receive);
  }, []);

  useEffect(() => {
    if (!open || !activeAgentId) return;
    let cancelled = false;
    setLoading(true);
    void listMediaLibrary(activeAgentId)
      .then((items) => {
        if (!cancelled) setTracks(items);
      })
      .catch((reason) => {
        if (!cancelled) setError(String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeAgentId, open]);

  if (!open) return null;
  const selectedTracks = tracks.filter((track) => selected.includes(track.sourceId));
  const toggle = (sourceId: string) => {
    setSelected((items) => items.includes(sourceId)
      ? items.filter((item) => item !== sourceId)
      : [...items, sourceId]);
  };
  const load = async (mode: "replace" | "append") => {
    if (!selectedTracks.length || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const count = await loadMediaTracks(activeAgentId, selectedTracks, {
        mode,
        autoplay: mode === "replace",
      });
      if (!count) throw new Error(t("mediaLibrary.loadFailed"));
      setOpen(false);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="media-library-backdrop" onMouseDown={() => setOpen(false)}>
      <section className="media-library-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>{t("mediaLibrary.title")}</h2>
            <p>{t("mediaLibrary.subtitle")}</p>
          </div>
          <button type="button" onClick={() => setOpen(false)} title={t("common.close")}>
            <Icon name="x" size={17} />
          </button>
        </header>
        <div className="media-library-body">
          {loading && <div className="media-library-state">{t("mediaLibrary.loading")}</div>}
          {!loading && !tracks.length && !error && (
            <div className="media-library-state">
              <Icon name="folder" size={25} />
              <strong>{t("mediaLibrary.empty")}</strong>
              <span>{t("mediaLibrary.emptyHint")}</span>
            </div>
          )}
          {error && <div className="media-library-state error">{error}</div>}
          {!loading && tracks.length > 0 && (
            <div className="media-library-list">
              {tracks.map((track) => {
                const checked = selected.includes(track.sourceId);
                return (
                  <button
                    type="button"
                    key={`${track.sessionId}:${track.sourceId}`}
                    className={checked ? "selected" : ""}
                    onClick={() => toggle(track.sourceId)}
                  >
                    <span className="media-library-check">{checked ? "✓" : ""}</span>
                    <span className="media-library-note">♫</span>
                    <span className="media-library-track">
                      <strong>{track.title || t("mediaPlayer.untitled")}</strong>
                      <small>{formatSize(track.size)}</small>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <footer>
          <span>{t("mediaLibrary.selected", { count: selected.length })}</span>
          <div>
            <Button variant="secondary" disabled={!selected.length || submitting} onClick={() => void load("append")}>
              {t("mediaLibrary.append")}
            </Button>
            <Button disabled={!selected.length || submitting} onClick={() => void load("replace")}>
              {t("mediaLibrary.replace")}
            </Button>
          </div>
        </footer>
      </section>
    </div>
  );
}
