export function sanitizeNotificationText(value: unknown, maxCodePoints: number): string {
  if (typeof value !== "string" || maxCodePoints <= 0) return "";

  const safeCharacters: string[] = [];
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (
      codePoint === 0x09
      || codePoint === 0x0a
      || codePoint === 0x0d
      || (codePoint !== undefined && codePoint >= 0x20 && codePoint <= 0xd7ff)
      || (codePoint !== undefined && codePoint >= 0xe000 && codePoint <= 0xfffd)
      || (codePoint !== undefined && codePoint >= 0x10000 && codePoint <= 0x10ffff)
    ) {
      safeCharacters.push(character);
    }
  }

  const normalized = safeCharacters.join("").replace(/\s+/g, " ").trim();
  const characters = Array.from(normalized);
  return characters.length > maxCodePoints
    ? `${characters.slice(0, maxCodePoints).join("")}...`
    : normalized;
}
