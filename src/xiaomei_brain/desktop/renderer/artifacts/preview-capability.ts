export type ArtifactPreviewKind = "image" | "docx" | "pdf" | "spreadsheet";

export interface PreviewableArtifact {
  kind?: string;
  name: string;
  mimeType?: string;
}

/** One capability table shared by message cards, artifact lists, and the workspace. */
export function artifactPreviewKind(artifact: PreviewableArtifact): ArtifactPreviewKind | null {
  const name = artifact.name.toLowerCase();
  const mimeType = (artifact.mimeType || "").toLowerCase();
  if (artifact.kind === "image" || mimeType.startsWith("image/")) return "image";
  if (name.endsWith(".docx") || mimeType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") return "docx";
  if (name.endsWith(".pdf") || mimeType === "application/pdf") return "pdf";
  if (
    name.endsWith(".xlsx")
    || name.endsWith(".xls")
    || mimeType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    || mimeType === "application/vnd.ms-excel"
  ) return "spreadsheet";
  return null;
}

export function supportsArtifactPreview(artifact: PreviewableArtifact): boolean {
  return artifactPreviewKind(artifact) !== null;
}
