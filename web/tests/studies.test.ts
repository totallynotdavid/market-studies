import { describe, expect, it } from "vitest";
import { repoUrl } from "../src/lib/repo-links";
import { lede, title } from "../src/lib/studies";

const ROOT = "/repo";
const README = "/repo/studies/bvl-liquidity/README.md";
const BLOB = "https://github.com/totallynotdavid/market-studies/blob/master/";

describe("a link in a study README", () => {
  it("points a file beside the README at it on GitHub", () => {
    expect(repoUrl("numbers.json", README, ROOT)).toBe(
      `${BLOB}studies/bvl-liquidity/numbers.json`,
    );
  });

  it("resolves a path that climbs out of the study folder", () => {
    expect(repoUrl("../../docs/BVL.md", README, ROOT)).toBe(
      `${BLOB}docs/BVL.md`,
    );
  });

  it("leaves absolute URLs, site paths and anchors alone", () => {
    for (const href of ["https://www.smv.gob.pe/", "/peru", "#findings"])
      expect(repoUrl(href, README, ROOT)).toBe(href);
  });
});

describe("the study list", () => {
  const markdown = [
    "# Do BVL prices move before a material event is filed?",
    "",
    "A Peruvian issuer must file each material event with the",
    "[SMV](https://www.smv.gob.pe/). The `events` table holds them.",
    "",
    "## Method",
  ].join("\n");

  it("takes the title from the first heading", () => {
    expect(title(markdown, "id")).toBe(
      "Do BVL prices move before a material event is filed?",
    );
  });

  it("takes the first paragraph as plain text", () => {
    expect(lede(markdown)).toBe(
      "A Peruvian issuer must file each material event with the SMV. The events table holds them.",
    );
  });
});
