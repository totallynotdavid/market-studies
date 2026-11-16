import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY =
  "https://github.com/totallynotdavid/market-studies/blob/master/";

function isRelative(href: string): boolean {
  return !/^([a-z][a-z0-9+.-]*:|\/|#)/i.test(href);
}

/** The GitHub URL of `href` as written in the markdown file `file`. */
export function repoUrl(href: string, file: string, root: string): string {
  if (!isRelative(href)) return href;
  const path = relative(root, resolve(dirname(file), href));
  return REPOSITORY + path.split("\\").join("/");
}

/**
 * A Sätteri hast plugin that points relative links in a repository markdown
 * file at the file on GitHub. A study's README links its numbers and the
 * manual as repository paths, which the site does not serve.
 */
export function repoLinks(root: string) {
  return {
    name: "repo-links",
    element: {
      filter: ["a"],
      visit(
        node: { properties: Record<string, unknown> },
        ctx: {
          fileURL: URL | undefined;
          setProperty(node: unknown, key: string, value: unknown): void;
        },
      ) {
        const href = node.properties.href;
        if (ctx.fileURL === undefined || typeof href !== "string") return;
        const url = repoUrl(href, fileURLToPath(ctx.fileURL), root);
        if (url !== href) ctx.setProperty(node, "href", url);
      },
    },
  };
}
