export type ArtifactPreviewKind = "image" | "docx" | "pdf" | "spreadsheet" | "text" | "markdown" | "html";

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
    || name.endsWith(".csv")
    || mimeType === "text/csv"
    || mimeType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    || mimeType === "application/vnd.ms-excel"
  ) return "spreadsheet";
  if (
    name.endsWith(".md")
    || name.endsWith(".markdown")
    || mimeType === "text/markdown"
  ) return "markdown";
  if (
    name.endsWith(".html")
    || name.endsWith(".htm")
    || mimeType === "text/html"
  ) return "html";
  if (name.endsWith(".txt") || mimeType === "text/plain") return "text";
  return null;
}

export function supportsArtifactPreview(artifact: PreviewableArtifact): boolean {
  return artifactPreviewKind(artifact) !== null;
}
