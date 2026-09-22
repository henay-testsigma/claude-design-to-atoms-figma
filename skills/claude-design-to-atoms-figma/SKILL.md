---
name: claude-design-to-atoms-figma
description: "Port a Claude-generated design (a .zip, a folder, a single .html, or a claude.ai artifact URL) into Figma as screens and flows, with every color, type, spacing and shadow value remapped onto an existing Figma design system (color styles, text styles, effect styles, variables) instead of raw hex values. Use when the user says: 'take this Claude design into Figma', 'import this artifact/zip/html into Figma', 'extract the screens and flows from this design', 'map these colors to our design system', 'push these screens to this Figma link', or gives a Claude design plus a Figma file/node URL to drop the screens into. Also use for the reverse-check: auditing screens already in Figma for hardcoded values that should be design system tokens."
---

# Claude design → Figma screens, flows, and design system tokens

Turn a Claude design deliverable into real Figma screens that are **linked to the user's design system** — not a pile of rectangles with hex fills. Three things must be true when you are done:

1. Every screen and every meaningful state in the design exists as a frame in Figma, laid out in flow order.
2. Every color, text, radius, spacing and shadow value resolves to a design system style/variable, or appears in an **unmapped list** the user has explicitly approved.
3. The user gets a per-screen list of Figma node links, placed at the location they asked for.

## Skill boundaries

- This skill owns: ingestion, screen/flow extraction, token mapping, placement, and the token-coverage audit.
- It does **not** re-implement Figma writes. Frame construction is delegated to the Figma skills — `figma-use` (API rules, mandatory before any `use_figma` call) and `figma-generate-design` (section-by-section screen assembly). Load both before writing to the canvas.
- Going the other way (Figma → code) is `figma-design-to-code`. Building new components/variants is `figma-generate-library`.

## Prerequisites

- Figma MCP connected. Batch-load the schemas in one call:
  `ToolSearch query="select:use_figma,get_screenshot,get_metadata,search_design_system,get_libraries,create_new_file,generate_figma_design"`
  **If that returns no matches and the only Figma tool you can see is `authenticate`, the MCP is not connected.** Call the plugin's `authenticate`, give the user the URL, and wait — do not start Phase 3 or 6 until the real tools appear. Check this at the very start; Phases 1, 2 and 5 can run while the user authorises.
- `search_design_system` currently **clamps a batched `queries` array to one query**. Issue several search calls in parallel rather than batching them.
- A target Figma **file key** and, ideally, a **target node** (page, section, or frame) to place screens under.
- The design system must already exist in the target file or a library linked to it.

## Inputs to confirm before starting

Ask only for what is missing — do not block on anything you can infer:

| Input | How to resolve |
|---|---|
| Design source | zip path, folder, `.html` file, or claude.ai artifact URL. For an artifact URL use the `Artifact` tool's `read` action, save the HTML locally, then treat it as a file. |
| Target Figma location (where screens are drawn) | **Never defaulted — always ask if it is missing.** Parse `fileKey` and `node-id` from the URL: `figma.com/design/<fileKey>/<name>?node-id=1-234` → nodeId `1:234`. If the user gives a file but no node, ask whether to create a new page or append to the current one. Do not fall back to the design system file. |
| Design system source (where tokens are read from) | Defaults to the **Atoms** file, `GLwCKePaKJEIEWzPsUOp1d`. Different from the target — see Phase 3. Only ask if the user implies another system. |
| Flow scope | Whether to import all screens or a named subset. Default: all. |
| Fidelity | `system` (default — design system instances/styles win, layout follows the design) or `pixel` (match the render exactly, tokens only where they already agree). State which one you used. |

## Workflow

Work through the phases in order. First set the two paths every phase uses:

```bash
# Where this skill is installed. Check these in order and use the first that exists —
# the skill may be installed per-user, per-project, or as part of a plugin.
SKILL=~/.claude/skills/claude-design-to-atoms-figma      # user-level install
# SKILL=./.claude/skills/claude-design-to-atoms-figma    # project-level install
# SKILL="$CLAUDE_PLUGIN_ROOT/skills/claude-design-to-atoms-figma"  # installed via a plugin

RUN=<scratchpad>/d2f/<slug>        # create this once, reuse it for every phase
```

If `$SKILL/scripts/ingest_design.py` is not there, locate the skill directory before going further rather than guessing a path.

### Phase 1 — Ingest and inventory

```bash
python3 "$SKILL"/scripts/ingest_design.py <source> --out "$RUN"
```

Unpacks the zip/folder/html, then writes `$RUN/inventory.json`: every HTML entry point, its `<title>`, size, inline vs linked CSS/JS, embedded images, whether it is a single-page app with client-side views, and detected framework (plain HTML, Tailwind CDN, React/Babel in-page, Vite build).

Read `inventory.json`, then read the actual markup for the entry points. **Do not skip reading the source** — the inventory tells you where to look, not what the design is.

**Bundler-wrapped artifacts.** A Claude design exported as a single HTML is often a *self-unpacking bundle*: a 1–2 MB file whose body is just `<div id="__bundler_thumbnail">` / `__bundler_loading` and a payload that JS inflates at runtime. Tell-tale signs — total visible text under ~200 characters, "This page requires JavaScript to display", `framework: ["react"]` with **no** `spa_signals`, and almost no colour literals. For these, static analysis can tell you nothing at all: Phases 2 and 5 **must** come from the render. Do not report "no flows found" from the static pass on such a file.

### Phase 2 — Extract the design's own tokens

```bash
python3 "$SKILL"/scripts/extract_tokens.py "$RUN" --out "$RUN/source-tokens.json"
```

Static pass — collects CSS custom properties, every color literal (hex/rgb/rgba/hsl/oklch), Tailwind arbitrary values (`bg-[#0f766e]`), font families, font-size/line-height pairs, border radii, spacing scale, and box-shadows, each with a use count and the files it appears in.

**Then get the ground truth from a render.** Static extraction misses anything computed, themed, or hidden behind a Tailwind class name:

```bash
python3 "$SKILL"/scripts/capture_screens.py "$RUN" --out "$RUN/capture" \
  --viewport 1440x900 [--states "$RUN/states.json"]   # states.json comes from Phase 2b
```

Per screen this writes a PNG plus `computed.json` (per-element computed color, background, font, size, line-height, radius, shadow, box geometry). If Playwright browsers are not installed the script prints the one-line install command and exits non-zero — run it, or fall back to the static pass and say so in your report. Merge computed values into `source-tokens.json` with `--merge-computed`.

### Phase 2b — Discover interaction states (required for SPA / bundled designs)

A single-screen app's "flows" are tabs, expanders, modals and toggles that exist only after JS runs. `extract_flows.py` reads markup and will find **zero** of them. Discover them from the live DOM instead:

```bash
python3 "$SKILL"/scripts/discover_states.py "$RUN" --out "$RUN/states.json"   --probe --max-probes 40
```

Without `--probe` it just lists interactive elements. With `--probe` it loads a fresh page per candidate, clicks it, and keeps only those that change a DOM signature — deduping states that land on the same view and skipping destructive labels (download, delete, submit…). The output feeds `capture_screens.py --states` directly.

Review the result: it finds *what changes the view*, not *what matters*. Drop states that are visually trivial, and add any it missed (elements behind a hover, a scroll, or two clicks deep — give those hand-written `actions` arrays).

### Phase 3 — Load the design system from Figma

Never guess the design system's values — read them and cache them. **Which file you read depends on where the system lives**, and getting this wrong is the single most common failure in this workflow:

| Setup | Read from | Why |
|---|---|---|
| System defined *in the target file* | the target `fileKey` | its styles are local there |
| System is a **linked library** (the usual case) | the **library's** `fileKey` | `getLocal*Async()` sees only the current file; library styles are remote and come back empty |

```
use_figma  →  $SKILL/scripts/inspect_design_system.js   (paste its contents as the script)
             run it against the file that OWNS the system, not the file you are drawing into
```

Save the result verbatim to `$RUN/design-system.json`.

**Default system: Atoms.** Unless the user names a different system, read it from the Atoms design system file — `fileKey` `GLwCKePaKJEIEWzPsUOp1d` ("Design System (New) - In Progress"). Its ramps are Primary, Secondary (GF), Secondary Unique, Neutral, Shades, Error, Warning, Section, Dark Mode, Dark Mode Blue, plus AI-1/AI-2 gradients; text styles are Title 1 (32/40), Title 2 (24/32), Page Popup header (18/28), Body normal, Body small, Monospace; effect styles include Inner Shadow / Shadow and a 00dp–24dp elevation-overlay set. Treat all of that as a hint for what to expect, never as values — always read the real hexes from the file.

**Library mode checklist** (system in one file, screens in another):

1. `get_libraries({ fileKey: <target> })` — confirm the system appears in `libraries_added_to_file`. If it is only in `libraries_available_to_add`, tell the user to add it in Figma first; you cannot link a library from the API.
2. The library must be **published**. Unpublished local styles still have `key` values, but `importStyleByKeyAsync` on them fails in the target file. If imports fail with a missing-key error, an unpublished (or newly edited, unpublished) style is the usual cause — say so rather than falling back to raw hexes.
3. Harvest names + `key`s by running the inspect script against the library file, then in the target file import by key: `figma.importStyleByKeyAsync(key)`, `figma.variables.importVariableByKeyAsync(key)`, `figma.importComponentSetByKeyAsync(key)`. Keys are stable across files; ids are not — never carry an `id` between files.
4. Cross-check with `search_design_system` using separate `{entity, query}` entries (one intent per query, never OR-packed), which *does* see remote libraries. Fold anything new into `design-system.json`.

**A system may have no variables at all.** Many mature Figma libraries are styles-only (paint/text/effect styles, zero variable collections). That is a valid system, not a failed read — but it means radii and spacing **cannot** be bound to tokens. Apply them as literals and say so in the report rather than claiming token coverage you did not achieve.

Cache `design-system.json` per **library** file key, not per target file — one read serves every screen import into every file that links it. Re-read when the user says the system changed.

### Phase 4 — Build the mapping ledger and get sign-off

```bash
python3 "$SKILL"/scripts/map_tokens.py \
  --source "$RUN/source-tokens.json" --system "$RUN/design-system.json" \
  --out "$RUN/mapping.json" --markdown "$RUN/MAPPING.md"
```

Matches each source value to the nearest design system token — colors by CIEDE2000 in Lab (not hex string distance), type by size+line-height+weight+family, radii/spacing/shadows numerically. Every row gets a confidence band:

- **exact** — identical value. Map it silently.
- **close** (ΔE ≤ 2.0, or type within 1px) — map it, list it in the summary.
- **far** (ΔE ≤ 10) — propose the nearest token, flag for review.
- **unmapped** (worse than that, or images with no equivalent) — never invent a token. Either keep the raw value and mark the node, or ask.
- **gradient-stop** — the value is a stop inside a gradient. Map the whole gradient to a gradient paint style; never map a stop to the nearest solid.

Values that appear only in the computed pass are often **browser defaults**, not design decisions (unstyled link blue, UA 16px text) — see `references/token-mapping.md` §6 before mapping them.

**Show the user `MAPPING.md` and get approval before writing to Figma** whenever there is a `far`, `unmapped` or `gradient-stop` row. That table is the contract for the whole import — a wrong mapping approved early is cheap, and a wrong mapping discovered after 20 screens is not. If every row is exact/close, say so and proceed without waiting.

Read `references/token-mapping.md` before interpreting the ledger — it covers semantic overrides that beat nearest-color (neutral vs primary greys, error/warning/success intent, dark-mode elevation overlays, AI gradients) and the type-style fallback order.

### Phase 5 — Extract flows

**Prototype scaffolding is not product design.** A Claude design often ships with authoring chrome — a view switcher, "Screen 1 / Screen 2" buttons, a reset-demo control. `discover_states.py` flags these (`prototypeChrome` on each candidate, plus `prototype_chrome_regions` with geometry). Clicking them is often how you reach the other views, so the views themselves are still real screens (tagged `via: "prototype-nav"`), but **the switcher must never be drawn into an imported frame** — exclude those regions when building.


```bash
python3 "$SKILL"/scripts/extract_flows.py "$RUN" --out "$RUN/flows.json" --markdown "$RUN/FLOWS.md"
```

Derives the screen graph: multi-file `<a href>` links, SPA route tables and hash routes, view-switching state (`setView`, `useState` screen enums, `data-screen`, `.screen.active`), modal/drawer/toast triggers, and form submit targets. Each node gets `{id, title, kind: screen|modal|state|empty|error, from[], to[], trigger}`.

Review `FLOWS.md` against the markup yourself — heuristics miss dynamic navigation. Add what is missing, then order the screens: entry point first, then breadth-first along the happy path, with modals/states placed directly right of their parent screen.

### Phase 6 — Place into Figma

Load `figma-use` and `figma-generate-design` now. Then:

1. **Resolve the anchor.** `get_metadata` on the target node. If it is a page, create a `SECTION` named `<Design name> — imported <YYYY-MM-DD>` in clear space to the right of existing content. If it is an existing section/frame, append inside it. Never drop frames at (0,0) on top of the user's work.
2. **Lay out the grid.** One frame per flow node, flow order left→right, one row per flow branch, 200px gutters, 400px between rows. Name frames `<NN> <Screen name>` and modals `<NN>.<n> <State name>` so the flow order survives in the layers panel.
3. **Build one screen per `use_figma` call**, following `figma-generate-design` Step 4 — import component sets/variables/styles in a single `Promise.all`, bind variables for fills/spacing/radii, set `textStyleId` from the mapped text style, `effectStyleId` for shadows. Apply `mapping.json` mechanically; do not re-decide colors per screen.

   **Read [references/fidelity.md](references/fidelity.md) before writing the first build script.** Non-negotiables:
   - **Auto-layout everywhere.** Every container is `figma.createAutoLayout()`; absolute x/y only positions the top-level screen frame. Push trailing actions right with a spacer frame set to `FILL`.
   - **Take geometry from `computed.json`, never by eye** — padding, gap, height, radius, font size/weight. Give controls a *fixed* measured height and let width hug.
   - **Borders and shadows.** Secondary buttons have a hairline *and* a soft shadow; tinted badges take a tinted border; tinted cards take a light (200/300) border, not the text colour; selected rows often use a 2px inset side edge.
   - **Reuse library components before hand-building.** Search for `button`, `badge`, `tab`, `link`, `input`, `table cell`, `tooltip`. Instantiate, screenshot and inspect each one: components can be stale (missing font so the label will not render, fixed width, an outdated brand colour). Use what fits, hand-build the rest, and report which you rejected and why. When a component carries its label in a variant, statuses it does not ship cannot be expressed — report the gap instead of forcing a wrong variant.
   - **Every icon in the source must exist in the output.** Rebuilding an icon+label pair as bare text is the most common omission — audit region by region against the render (`scripts/extract_icons.py` counts them). If the library has no match, extract the SVG from the render and insert it with `figma.createNodeFromSvg()`.
   - **Icons are component instances, never emoji and never text glyphs.** Material Symbols: pick `style=outlined, weight=500` explicitly — the default variant is weight 100. **Minimum 16x16**, always. Colour only the vector children; painting the instance frame produces a solid block.
   - **Word gaps.** Figma trims trailing spaces in hugging text, so split colour segments run together. Trim segments and use `itemSpacing`, or use one text node with `setRangeFillStyleId`.
4. **Images.** `use_figma` cannot fetch URLs. If the design has images, run `generate_figma_design` against the **same fileKey** in parallel with step 3, then copy `imageHash` values from the capture's image fills onto your frames and delete the capture. Embedded data-URI images still need this path.
5. **Flow connectors.** Design files have no FigJam connectors. Draw flow arrows as thin vector/line + label text grouped in a `Flow` frame behind the screens, or add a `## Flow` text block listing transitions. Ask which the user prefers if the flow has more than ~8 edges.

### Phase 7 — Validate

**Run `scripts/verify_screen.js` through `use_figma` on every screen, and fix everything it reports, BEFORE showing the user anything.** Set `ROOT_ID` to the screen frame. It returns a defect list plus `PASS` (true when there are no high-severity defects). A screen is not done until `PASS` is true.

It checks, automatically, every class of defect that otherwise comes back as review feedback:

| Check | Severity | Catches |
|---|---|---|
| `untokenised-fill/stroke/text/effect` | high | values not bound to a design system style |
| `stray-container-fill` | high | the default white fill on a layout container |
| `child-overflows-parent` | high | a badge or link pushed past the card edge by a FILL spacer |
| `emoji-in-text` / `glyph-used-as-icon` | high | icons faked with text |
| `icon-placeholder` | high | an icon left as a plain frame |
| `zero-size-text` | high | text collapsed by a sizing mistake |
| `missing-font-invisible-text` | high | a label inside an instance that may paint nothing because its font is not installed |
| `missing-font-substituted` | medium | text rendering in a fallback typeface because the system's font is not installed locally — report it, it is an environment gap, not a build error |
| `icon-below-minimum` | medium | icons under 16px |
| `inner-frame-clips` | medium | a frame cropping child shadows |
| `labels-not-on-one-baseline` | medium | a decoration shifting its own label |

Iterate: run, fix, re-run. Report the final numbers honestly — coverage, remaining defects, and anything untokenisable (e.g. radii when the system has no variables).

Then the visual pass:

1. `get_screenshot` **per screen frame** (not one zoomed-out shot) and compare against `$RUN/capture/<screen>.png`. Fix with targeted calls; never rebuild a whole screen.
2. Assert fonts: the rendered family must be the design's family (from Phase 2), not Inter-by-default.
3. **Token coverage audit** — run `$SKILL/scripts/audit_tokens.js` through `use_figma` against the imported section. It returns every fill, stroke, text, radius and effect that is *not* bound to a variable or style, with node IDs. Target: zero, minus the rows the user approved as unmapped. Report the number both ways.
4. Re-run the audit after fixes, and report the final coverage figure honestly — if something could not be tokenized, name it.

### Phase 8 — Report

Give the user:

- The section link: `https://figma.com/design/<fileKey>/?node-id=<section-id>` plus a per-screen table of name → node link.
- Token coverage: `N/M values mapped to the design system`, and the unmapped list with the reason for each.
- Flow summary: screen count, edge count, anything you could not resolve from the markup.
- Paths to `$RUN/MAPPING.md` and `$RUN/FLOWS.md` for review.

## Re-runs and updates

When the user iterates on the design and re-imports, do not duplicate the section. Read the existing section, diff screen names against the new `flows.json`, then update changed screens in place (`figma-generate-design` Step 6), add new ones to the right, and mark removed ones `[deprecated]` rather than deleting — the user may have annotations on them. Keep `mapping.json` from the prior run so token decisions stay stable across imports.

## Failure modes to avoid

- **Hardcoding hexes because a search returned empty.** An empty `getLocalVariableCollectionsAsync()` means "no *local* variables", not "no variables". Always also `search_design_system`.
- **Nearest-color-wins on semantics.** A muted grey-green in an error banner maps to Error, not Primary. `references/token-mapping.md` has the override rules.
- **One giant `use_figma` script.** One screen per call, return node IDs from every call.
- **Skipping the render.** A Tailwind-CDN design has almost no color literals in its markup; the computed capture is where the real values live.
- **Reporting "done" off a thumbnail.** `verify_screen.js` returning `PASS`, plus a per-frame screenshot comparison, are the completion criteria.
- **Letting the reviewer find mechanical defects.** Overflow, stray fills, glyph icons, sub-16px icons and baseline drift are all machine-detectable. If a human is reporting them, the verifier was not run.
- **Estimating spacing.** If a padding or radius in your script is not traceable to `computed.json`, it is a guess and it will read as wrong.
- **Flat output.** Missing 1px hairlines and soft shadows is the most common reason a rebuild looks "off" even when colours and text are right.
- **Emoji or glyph icons.** Always instances from the icon library.

## References

- `references/token-mapping.md` — semantic mapping rules, type fallback order, dark mode/elevation, gradients.
- `references/flow-extraction.md` — the navigation patterns Claude designs use and how each maps to a flow edge.
- `references/placement.md` — anchor resolution, grid math, naming, connectors, re-run diffing.
- `references/fidelity.md` — measured geometry, borders/shadows, icon components, auto-layout and text-spacing rules. Read before building.
