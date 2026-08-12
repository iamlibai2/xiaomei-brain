import type { DesktopSettings } from "../../types";

export type MusicPlayerSkinId = DesktopSettings["musicPlayerSkin"];

export type MusicPlayerSkinDefinition = {
  id: MusicPlayerSkinId;
  labelKey: string;
  descriptionKey: string;
};

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
