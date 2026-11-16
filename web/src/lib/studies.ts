/** The first paragraph after the title of a study README, as plain text. */
export function lede(markdown: string): string {
  const paragraph = markdown
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .find((block) => block !== "" && !block.startsWith("#"));
  return (paragraph ?? "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[`*_]/g, "")
    .replace(/\s+/g, " ");
}

/** The text of the README's first `#` heading, or `fallback`. */
export function title(markdown: string, fallback: string): string {
  return /^#\s+(.+)$/m.exec(markdown)?.[1].trim() ?? fallback;
}
