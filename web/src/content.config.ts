import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";

// Each study folder at the repository root holds a README written by hand and
// the figures `bvl study` draws; the site renders that README as it stands.
const studies = defineCollection({
  loader: glob({
    base: "../studies",
    pattern: "*/README.md",
    generateId: ({ entry }) => entry.split("/")[0],
  }),
});

export const collections = { studies };
