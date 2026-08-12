import type { DesktopSettings } from "../../types";

export type MusicPlayerSkinId = DesktopSettings["musicPlayerSkin"];

export type MusicPlayerSkinDefinition = {
  id: MusicPlayerSkinId;
  labelKey: string;
  descriptionKey: string;
};

let activeSkin: MusicPlayerSkinId = "default";
let skinRevision = 0;
let skinHydrated = false;
let skinHydration: Promise<void> | null = null;
const skinListeners = new Set<() => void>();

export function getMusicPlayerSkinSnapshot(): MusicPlayerSkinId {
  return activeSkin;
}

export function subscribeMusicPlayerSkin(listener: () => void): () => void {
  skinListeners.add(listener);
  return () => skinListeners.delete(listener);
}

export function setActiveMusicPlayerSkin(nextSkin: MusicPlayerSkinId): void {
  if (activeSkin === nextSkin) return;
  activeSkin = nextSkin;
  skinRevision += 1;
  skinListeners.forEach((listener) => listener());
}

export function hydrateMusicPlayerSkin(
  load: () => Promise<unknown>,
): Promise<void> {
  if (skinHydrated) return Promise.resolve();
  if (skinHydration) return skinHydration;
  const revisionAtStart = skinRevision;
  skinHydration = load()
    .then((value) => {
      if (revisionAtStart === skinRevision && isMusicPlayerSkin(value)) {
        setActiveMusicPlayerSkin(value);
      }
    })
    .catch(() => undefined)
    .finally(() => {
      skinHydrated = true;
      skinHydration = null;
    });
  return skinHydration;
}

/**
 * Built-in player skins are code-owned UI, not arbitrary HTML artifacts.
 * This keeps playback controls available even when a generated visualization
 * is deleted, malformed, or belongs to another Person.
 */
export const MUSIC_PLAYER_SKINS: readonly MusicPlayerSkinDefinition[] = [
  {
    id: "default",
    labelKey: "mediaPlayer.skins.default",
    descriptionKey: "mediaPlayer.skins.defaultHint",
  },
  {
    id: "vinyl",
    labelKey: "mediaPlayer.skins.vinyl",
    descriptionKey: "mediaPlayer.skins.vinylHint",
  },
  {
    id: "visualization",
    labelKey: "mediaPlayer.skins.visualization",
    descriptionKey: "mediaPlayer.skins.visualizationHint",
  },
];

export function isMusicPlayerSkin(value: unknown): value is MusicPlayerSkinId {
  return value === "default" || value === "vinyl" || value === "visualization";
}
