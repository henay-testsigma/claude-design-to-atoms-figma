# claude-design-to-atoms-figma

A [Claude Code](https://claude.com/claude-code) skill that takes a Claude-generated design — a `.zip`, a folder, a single `.html`, or a claude.ai artifact URL — and rebuilds it in Figma as screens and flows, with **every color, type, radius and shadow value remapped onto your design system** instead of raw hex values.

The problem it solves: pasting a generated design into Figma gives you a pile of rectangles with hardcoded hexes. Nothing is linked to your library, so nothing updates when the system changes, and a designer has to redo it by hand. This skill makes token mapping the center of the workflow rather than an afterthought.

## What it does

1. **Ingest** — unpacks the design, finds entry points, detects Tailwind-CDN / in-page React / Vite builds, flags single-page designs whose screens are client-side views.
2. **Extract source tokens** — a static pass over the markup, then a **headless render** that reads *computed* styles per element. The render matters: a Tailwind-CDN design has almost no color literals in its source, so the real values only exist after the browser resolves them.
3. **Read your design system** — dumps paint styles, text styles, effect styles, variable collections and component keys from the file that owns your system. No values are ever hardcoded.
4. **Mapping ledger** — matches colors by **CIEDE2000 in CIELAB** (not hex-string proximity), type by size + line-height + weight + family. Every row is banded `exact` / `close` / `far` / `unmapped` / `gradient-stop`, written to a reviewable `MAPPING.md`, and **you approve it before anything is written to Figma**.
5. **Flow extraction** — derives the screen graph from links, route tables, hash routers, `setView` state enums, and modal/empty/error markers, then orders the screens for a left-to-right flow.
6. **Place into Figma** — resolves your target node, creates a dated section in clear space, and builds one frame per screen using your components, styles and variables (delegating canvas writes to the official `figma-use` / `figma-generate-design` skills).
7. **Audit** — reports every fill, stroke, text, radius and effect *not* bound to a style or variable, so token coverage is a measured number rather than a claim.

## Install

### As a skill (simplest)

```bash
git clone https://github.com/henaylakhwani-design/claude-design-to-atoms-figma.git
cp -R claude-design-to-atoms-figma/skills/claude-design-to-atoms-figma ~/.claude/skills/
```

Restart Claude Code, then run `/claude-design-to-atoms-figma`.

### As a plugin (gets updates)

```
/plugin marketplace add henaylakhwani-design/claude-design-to-atoms-figma
/plugin install claude-design-to-atoms-figma@henay-design-skills
```

### Per project (ships with a repo)

```bash
mkdir -p .claude/skills
cp -R claude-design-to-atoms-figma/skills/claude-design-to-atoms-figma .claude/skills/
```

Commit it, and everyone who clones the repo gets the skill.

## Requirements

| Requirement | Why |
|---|---|
| Figma MCP server connected | all Figma reads and writes |
| `figma-use` + `figma-generate-design` skills | this skill delegates canvas writes to them |
| Python 3.8+ | the analysis scripts (stdlib only, no install) |
| Playwright + Chromium | renders each screen to read computed styles |
| Your design system published as a Figma library, added to the target file | tokens import by key; unpublished keys fail to import |

```bash
pip3 install playwright && python3 -m playwright install chromium
```

Playwright is strongly recommended rather than truly optional — without it, a Tailwind-based design yields very little to map.

## Pointing it at your own design system

It defaults to the Atoms design system file, but **nothing about the skill is Atoms-specific** — no hex values, style names or component names are hardcoded anywhere; they are always read live from Figma. To retarget it, change the default `fileKey` in `SKILL.md` Phase 3, or just pass your own file when you run it.

Phase 3 handles the case most workflows get wrong: if your system is a **linked library** rather than part of the target file, Figma's `getLocal*Async()` APIs return an empty system, because they only see the current file. The skill reads from the file that *owns* the system, harvests style/variable `key`s there, and imports by key into the target — keys are stable across files, ids are not.

## Design decisions worth knowing

- **Semantics beat nearest-color.** A muted red in an error banner maps to your Error ramp, not Primary — reds and ambers sit close in Lab space, so pure distance gets this wrong.
- **Elevation maps by intent, not by literal `box-shadow`.** Systems that express elevation as overlay percentages want a dp step, and dark-mode elevation is a *lighter surface*, not a darker shadow.
- **Browser defaults are not design intent.** Unstyled link blue (`#0000EE`) and UA `16px` text show up in the computed pass and must be mapped by role, not accepted literally.
- **Gradient stops are never mapped to solids.** They route to gradient paint styles or stay flagged.
- **The ledger is the contract.** Once approved it is applied mechanically to every screen, so the same design value always lands on the same token — including across re-imports.

See `skills/claude-design-to-atoms-figma/references/` for the full rules on token mapping, flow extraction, and placement.

## Notes

- `scripts/*.js` are pasted as `use_figma` scripts and use top-level `await`, because `use_figma` wraps them in an async context. `node --check` will reject them; that is expected.
- Re-running an import updates screens in place rather than duplicating them, and marks removed screens `[deprecated]` instead of deleting — reviewers may have comments pinned to those nodes.

## License

MIT
