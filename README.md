# claude-design-to-atoms-figma

A [Claude Code](https://claude.com/claude-code) skill that takes a Claude-generated design — a `.zip`, a folder, a single `.html`, or a claude.ai artifact URL — and rebuilds it in Figma as screens and flows, with **every color, type, radius and shadow value remapped onto your design system** instead of raw hex values.

The problem it solves: pasting a generated design into Figma gives you a pile of rectangles with hardcoded hexes. Nothing is linked to your library, so nothing updates when the system changes, and a designer has to redo it by hand. This skill makes token mapping the center of the workflow rather than an afterthought.

## What it does

1. **Ingest** — unpacks the design, finds entry points, detects Tailwind-CDN / in-page React / Vite builds, and recognises self-unpacking Claude artifacts whose markup is invisible until JS runs.
2. **Extract source tokens** — a static pass, then a **headless render** that reads *computed* styles per element. The render matters: a Tailwind design has almost no colour literals in its source.
3. **Discover states** — enumerates interactive elements in the rendered DOM and probes them, including **nested states** (`--depth 2`) that only exist once a modal is open. It also flags prototype scaffolding so authoring chrome never gets drawn into a screen.
4. **Read your design system** — pulls paint/text/effect styles, variables and component keys from the file that *owns* the system. No values are hardcoded.
5. **Mapping ledger** — colours matched by CIEDE2000 in CIELAB, type by size + line-height + weight + family, banded `exact` / `close` / `far` / `unmapped` / `gradient-stop` into a reviewable `MAPPING.md` you approve before anything is written.
6. **Build** — one frame per state, grouped into Figma sections by page variant, using your components, styles and icon library throughout.
7. **Two quality gates** — see below.

## Quality gates

A screen is not done until both pass:

**Completeness** — `compare_to_capture.py` diffs the built frame's text against the captured source state. A screen can be perfectly tokenised and still be *underbuilt* — a grey placeholder where the source has a whole rebuilt region. That is invisible to a style audit but trivially measurable.

**Correctness** — `verify_screen.js` runs 19 checks in Figma and returns a ranked defect list plus `PASS`:

`untokenised-fill/stroke/text/effect` · `stray-container-fill` · `child-overflows-parent` · `content-clipped` · `emoji-in-text` · `glyph-used-as-icon` · `icon-placeholder` · `icon-below-minimum` · `zero-size-text` · `missing-font-invisible-text` · `missing-font-substituted` · `modal-without-close` · `frame-taller-than-content` · `inner-frame-clips` · `labels-not-on-one-baseline`

Every one of these exists because it was found by a human reviewer first. The point of the skill is that it never needs to be again.

## Install

### As a skill (simplest)

```bash
git clone https://github.com/henay-testsigma/claude-design-to-atoms-figma.git
cp -R claude-design-to-atoms-figma/skills/claude-design-to-atoms-figma ~/.claude/skills/
```

Restart Claude Code, then run `/claude-design-to-atoms-figma`.

### As a plugin (gets updates)

```
/plugin marketplace add henay-testsigma/claude-design-to-atoms-figma
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

## Scripts

| Script | Purpose |
|---|---|
| `ingest_design.py` | unpack and inventory the design |
| `capture_screens.py` | headless render: PNG + computed styles per state |
| `discover_states.py` | find interaction states, including nested ones (`--depth 2`) |
| `extract_tokens.py` | collect the design's own colour/type/spacing values |
| `extract_flows.py` | derive the screen graph |
| `extract_icons.py` | pull inline SVGs for icons the library lacks |
| `map_tokens.py` | match source values to design system tokens (CIEDE2000) |
| `inspect_design_system.js` | read styles/variables/components out of Figma |
| `compare_to_capture.py` | **completeness gate** — text parity vs the source |
| `verify_screen.js` | **correctness gate** — 19 automated checks |
| `audit_tokens.js` | standalone token-coverage audit |

## Notes

- `scripts/*.js` are pasted as `use_figma` scripts and use top-level `await`, because `use_figma` wraps them in an async context. `node --check` will reject them; that is expected.
- Re-running an import updates screens in place rather than duplicating them, and marks removed screens `[deprecated]` instead of deleting — reviewers may have comments pinned to those nodes.

## License

MIT
