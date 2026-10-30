import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Vitest runs from app/web/, and jsdom rewrites import.meta.url, so resolve from cwd.
const css = readFileSync(resolve("src/styles/tokens.css"), "utf8").toLowerCase();

const tokens: Record<string, string> = {
  "--navy": "#081b59",
  "--ink": "#0f1f33",
  "--orange": "#ee5e27",
  "--amber": "#f79829",
  "--peach": "#f6d4b1",
  "--paper": "#f5f4f2",
  "--muted": "#4f5b70",
  "--line": "#e2ded8",
  "--amber-bg": "#fde9cc",
  "--amber-ink": "#6b3a00",
  "--pos": "#2f7a55",
  "--font-sans": "montserrat, system-ui, sans-serif",
  "--font-display": '"gilda display", serif',
};

describe("tokens", () => {
  it.each(Object.entries(tokens))("tokens match the brand: %s", (name, value) => {
    expect(css).toContain(`${name}: ${value};`);
  });
});
