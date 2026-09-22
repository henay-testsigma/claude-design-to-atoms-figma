# Placement, naming, and re-runs

## Resolving the anchor from a Figma URL

```
https://www.figma.com/design/GLwCKePaKJEIEWzPsUOp1d/My-File?node-id=1234-5678
                             └── fileKey ──────────┘             └ nodeId 1234:5678
```

Hyphen → colon in the node id. `node-id=0-1` is the file's first page, which means "no specific target" — treat it as *the file*, and ask where inside it.

Then `get_metadata` on the node and branch on its type:

| Anchor type | What to do |
|---|---|
| PAGE | create a `SECTION` in clear space to the right of all existing children |
| SECTION | build inside it; if it already has imported screens, go to the re-run path |
| FRAME | build inside it only if it is empty or clearly a container; otherwise create a sibling section next to it |
| COMPONENT / INSTANCE | do not build inside. Create a section on the same page and say why |

Find clear space, never (0,0):

```js
let maxX = 0;
for (const c of figma.currentPage.children) maxX = Math.max(maxX, c.x + c.width);
section.x = maxX + 400;
```

Remember `figma.currentPage` resets to the first page on every `use_figma` call — `await figma.setCurrentPageAsync(page)` at the top of each script that targets another page.

## Grid math

- Screen frame width = the captured viewport width (1440 desktop, 390 mobile). Height = the capture's `scrollHeight`, so full-page designs are not cropped.
- Horizontal gutter 200px, vertical gutter 400px between flow rows.
- Modals/states sit in the row **below** their parent screen, left-aligned to it.
- The section title carries the run info: `<Design name> — imported <YYYY-MM-DD>`.

## Naming

```
01 Dashboard
01.1 Dashboard · Empty
01.2 Dashboard · Filters modal
02 Test detail
02.1 Test detail · Delete confirm
```

Zero-padded ordinals keep the layers panel in flow order. Use `·` to separate screen from state — it reads well and never collides with a screen name.

## Flow arrows in a design file

Design files have no connectors (that is FigJam). Options, cheapest first:

1. A `Flow` text block in the section listing `From → Trigger → To`. Always do this — it survives layout changes.
2. Thin lines (2px, Neutral 300) plus small label text, grouped in one `Flow` frame placed *behind* the screens. Good up to ~8 edges.
3. For a dense graph, build the map in a FigJam board instead and link the two files.

## Re-runs

1. Find the existing section by name prefix.
2. Diff its child frame names against the new `flows.json` order.
3. Same name → update in place (`figma-generate-design` Step 6): swap instances, set text, adjust layout. Do not delete and rebuild — the user may have comments pinned to those nodes.
4. New name → append to the right of the last frame in its row.
5. Gone → rename to `[deprecated] <name>`, move to the bottom row. Deleting is the user's call, not yours.
6. Keep the previous `mapping.json` so token decisions do not drift between imports.
