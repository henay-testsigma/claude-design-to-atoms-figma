# Build fidelity — the details that get missed

Every rule here comes from a real import that got it wrong first. Work through this list before declaring a screen done.

## 1. Never estimate geometry — read it from the capture

`capture_screens.py` records `padding`, `gap`, `w`/`h`, `borderRadius`, `borderWidth`, `borderColor` and `boxShadow` for every element. **Use them.** Eyeballing "looks like 12px padding, radius 8" is the single largest source of "it doesn't look like the design".

Pull the real numbers before building:

```bash
python3 - <<'PY'
import json
d=json.load(open("RUN/capture/SCREEN.computed.json"))
for e in d["elements"]:
    t=(e.get("text") or "").strip()
    if t in ("Compare","Ignore","Approve"):     # the components you are about to build
        print(t, "%dx%d"%(e["w"],e["h"]), e["borderRadius"], e["padding"],
              e["gap"], e["fontSize"]+"/"+e["fontWeight"], e["boxShadow"])
PY
```

A real example of estimate vs. measured, from one screen:

| Property | Estimated | Measured | Visible effect |
|---|---|---|---|
| Button height | hug (~32) | **28 fixed** | buttons too tall, rows misaligned |
| Button radius | 6–8 | **5** | corners too round |
| Button padding | 12–14 | **0 11** | too wide, wrong rhythm |
| Button label | 13px | **12px / 500** | text too large |
| Toolbar gap | 12 | **14** | crowded |

Set a **fixed height** on buttons/badges/chips (`layoutSizingVertical = "FIXED"` then `resize`) and let width hug the label. Hugging both axes makes every control a different height.

## 2. Borders and shadows are almost always missed

Flat-looking output is usually missing 1px hairlines and very soft shadows. Check `borderWidth`, `borderColor`, `boxShadow` on every surface, and note these patterns:

| Element | What it actually has |
|---|---|
| Secondary / white buttons | 1px neutral hairline **and** a soft shadow (`rgba(0,0,0,0.06) 0 1px 1px`) |
| Primary / filled CTA | no border, slightly stronger shadow (`rgba(0,0,0,0.12)`) |
| Tinted status badges | a **tinted** border matching the badge (red badge → light red border), never the neutral one |
| Tinted cards (success/warning) | a **light** tint border — map to the ramp's 200/300 step, never the 500/600 you used for the text |
| Selected / active rows | often an inset side edge: `rgb(...) 2px 0 0 inset` → a 2px left stroke, not a full border |
| Segmented controls | the *selected pill* carries the shadow; the track does not |

For a single-side border use per-side stroke weights:

```js
n.strokeStyleId = errorStyle.id;
n.strokeAlign = "INSIDE";
n.strokeTopWeight = 0; n.strokeBottomWeight = 0; n.strokeRightWeight = 0;
n.strokeLeftWeight = 2;
```

**Hairlines are often 0.5px, not 1px.** A control that reads as a crisp hairline on a retina render is usually a half-pixel stroke; setting 1px makes every button look heavier than the design. Use `strokeWeight = 0.5` with `strokeAlign = "INSIDE"` for button/badge/chip outlines, and reserve 1px for genuine dividers.

**Frames clip by default, which crops child shadows.** A button's drop shadow disappears or cuts off at its row's edge because the parent frame has `clipsContent = true`. After building a screen, sweep every descendant frame and set `clipsContent = false`, leaving it `true` only on the outer screen frame:

```js
for (const f of screen.findAll(() => true)) {
  if ("clipsContent" in f && f.id !== screen.id) f.clipsContent = false;
}
screen.clipsContent = true;
```

Symptom to watch for: shadows that look fine on an isolated node screenshot but vanish or square off in the full screen.

A border's colour is a *token*, not the same token as the fill: a green card is `Primary/50` fill + `Primary/300` border + `Primary/600` text. Using one green for all three is the classic tell.

## 3. Icons: real components, never glyphs or emoji

**Never use emoji, and never fake an icon with a text glyph** (`✕`, `✎`, `▾`). Use the project's icon library.

For **Material Symbols**, the component set exposes two variant properties:

```
style:  outlined | outlined-filled | rounded | rounded-filled | sharp | sharp-filled
weight: 100 | 200 | 300 | 400 | 500 | 600 | 700
```

The default variant is `weight=100` — far too light. Select explicitly:

```js
const set = await figma.importComponentSetByKeyAsync(KEY);
const variant = set.children.find((c) => c.name === "style=outlined, weight=500")
  || set.defaultVariant;
const inst = variant.createInstance();
inst.layoutSizingHorizontal = "FIXED";
inst.layoutSizingVertical = "FIXED";
inst.resize(16, 16);
```

**Type-size floor.** A design system's smallest text style may be larger than the source's smallest size (e.g. source uses 11px, the system's smallest is 12px). Controls built from it will be slightly wider than the original — a pill measured at 120px may come out 137px. This is correct behaviour (the system wins over the mock), but say so in the report rather than letting it read as a layout bug.

**Minimum icon size is 16x16.** Never place a 12 or 14px icon — below 16 the Material Symbols geometry loses legibility and rows stop aligning to the 16px rhythm. Set both axes `FIXED` and `resize(16, 16)` (or larger), and sweep the screen at the end to catch any that slipped through.

Colour an instance by walking its descendants and setting `fillStyleId` on every node with fills — setting it on the instance alone does not always reach the vectors.

**Audit for missing icons before calling a screen done.** The most common icon defect is not a wrong icon but an *absent* one — a toolbar rebuilt as plain text when the source pairs every label with a glyph. Cross-check against the render: count the `<svg>` elements in a region and make sure the same number of icon nodes exists in Figma. `scripts/extract_icons.py` prints that inventory.

**Fallback when the library has no match:** pull the real SVG out of the render and insert it directly.

```bash
python3 "$SKILL"/scripts/extract_icons.py "$RUN" --out "$RUN/icons"
```

It writes one deduped `.svg` per distinct icon plus `icons.json` (nearest label, size, colour, use count) so each maps to the right slot. Insert with:

```js
const node = figma.createNodeFromSvg(svgText);
node.name = "Icon / <name>";
node.resize(16, 16);                     // never below 16
for (const c of node.findAll(() => true)) {
  if (c.type === "VECTOR") c.fillStyleId = colourStyle.id;
}
```

Use the library first and this only for genuine gaps — an imported SVG is a detached vector that will not track the design system.

Icons are found with `search_design_system` by their Material name (`chevron_right`, `check_circle`, `cancel`, `edit`, `thumb_up`, `thumb_down`). **The server clamps a batched `queries` array to one query**, so issue several search calls in parallel instead of batching.

## 4. Auto-layout everywhere — stacks, not coordinates

Every container is `figma.createAutoLayout()`. Absolute `x`/`y` is only for placing a top-level screen frame on the canvas. A screen is a vertical stack of regions; each region is a horizontal or vertical stack; rows use a spacer frame with `layoutSizingHorizontal = "FILL"` to push trailing actions right.

## 5. `resize()` resets sizing modes — order matters

This silently breaks full-width layouts:

```js
// WRONG — resize() reverts the node to FIXED, so it never fills
spacer.layoutSizingHorizontal = "FILL";
spacer.resize(10, 1);

// RIGHT — size first, then declare how it should behave in the stack
spacer.resize(10, 1);
spacer.layoutSizingVertical = "FIXED";
spacer.layoutSizingHorizontal = "FILL";
```

The symptom is a header whose actions bunch up next to the title instead of sitting at the far right, or a bar that stops short of the frame edge. There is no error — the layout just looks wrong. Whenever a row should span the frame, assert it afterwards: read the node's `width` back and compare it to the screen width.

The same ordering trap applies to any node you both resize and set to `HUG`/`FILL`. Append to the auto-layout parent, resize, *then* set the sizing mode.

## 6. Figma trims trailing spaces in hugging text

Splitting a label into coloured segments (`"Tap on "` + `"Send OTP"`) renders as `Tap onSend OTP`, because a hugging text node's width ignores trailing whitespace. Two fixes:

- Trim each segment and let the row's `itemSpacing` (≈4px at 13px type) supply the word gap. Simple, keeps one node per colour.
- Or use a single text node and `setRangeFillStyleId(start, end, styleId)`. Fewer nodes, exact spacing, more code.

Never rely on a trailing space inside a hugging text node.

## 7. Apply text styles LAST when the style's font is not installed

If the design system's style uses a font you do not have locally (e.g. `SF Mono`), you can still *apply* the style — but any write to that node afterwards throws:

```
Cannot write to node with unloaded font "SF Mono Regular"
```

So `textAutoResize`, `layoutSizing*`, or a characters edit after applying the style will fail mid-script and leave a half-built screen. Build every text node with a font you know is loadable, do all layout mutations, then apply `textStyleId` in a final pass:

```js
const pending = [];
const txt = (chars, styleKey, colourKey) => {
  const t = figma.createText();
  t.fontName = { family: "SF Pro", style: "Regular" };   // known-loadable
  t.characters = chars;
  t.fillStyleId = P[colourKey].id;
  pending.push([t, styleKey]);                            // defer the style
  return t;
};
// ... build and lay out everything ...
for (const [node, key] of pending) node.textStyleId = S[key].id;
```

## 8. Re-hug controls after applying text styles

A control sized with `resize()` *before* its label's style was applied keeps a stale hug width, and the label clips once the style makes the text wider. After the deferred style pass, re-hug horizontally while keeping the measured fixed height:

```js
const h = n.height;
n.layoutSizingHorizontal = "HUG";
n.layoutSizingVertical = "FIXED";
n.resize(n.width, h);
```

## 9. Layout containers must be transparent

`figma.createAutoLayout()` and `figma.createFrame()` give every container an **opaque white fill**. Left alone these are invisible on a white page but they are real untokenised fills — they wreck the coverage audit and they show as white boxes over any tinted parent. Only surfaces carry a fill style; wrappers get `fills = []`. Sweep before auditing:

```js
for (const n of root.findAll(() => true)) {
  if (n.type !== "FRAME" || n.id === root.id) continue;
  if (n.fillStyleId && n.fillStyleId !== figma.mixed) continue;   // intentionally styled
  if (Array.isArray(n.fills) && n.fills.length) n.fills = [];
}
```

In one real screen this cleared 74 stray fills and moved token coverage from 81.4% to 93.5%.

## 10. A FILL spacer cannot shrink — it pushes trailing content out of the frame

The spacer idiom (`spacer.layoutSizingHorizontal = "FILL"`) works only when the row has slack. When the row's intrinsic content is *wider* than the frame, the spacer refuses to go below its minimum and the trailing element overflows past the edge, clipped by the card.

Symptom: a status pill or action button hanging off the right edge of a card that is itself correctly sized.

Fix: drop the spacer and make the naturally-flexible element (usually a date, filename or title) absorb the slack *and* be allowed to truncate:

```js
dateText.textAutoResize = "HEIGHT";
dateText.layoutSizingHorizontal = "FILL";
dateText.textTruncation = "ENDING";
dateText.maxLines = 1;
```

Cap any other greedy child with a FIXED width so it cannot dominate. Then verify by summing: children + gaps + padding must equal the frame width. In one real header: 120 + 77 + 60 + 16 gaps + 24 padding = 297 = the card width, exactly.

**Always verify a row fits by reading widths back**, rather than trusting that it looks fine at a zoomed-out scale.

## 11. Decorations must not shift the thing they decorate

A tab's underline, a selected indicator, a badge dot — anything stacked with a label inside an auto-layout column changes that column's height, and therefore where centring puts the label. The result: the active tab's text sits a few pixels off from its neighbours and from anything else in the row.

Two rules keep a control row on one baseline:

1. **Every item in the group keeps identical structure.** Do not remove the underline from inactive tabs — keep it in the layout and make it transparent (`visible = true`, `fills = []`). A hidden child (`visible = false`) is excluded from auto-layout, so hiding it changes that tab's height and moves its label.
2. **Anchor the label, not the block.** Give each column a fixed height equal to the row, `primaryAxisAlignItems = "MIN"`, and a measured `paddingTop`. The label's position is then governed by the padding alone and the decoration can never move it.

```js
tab.layoutSizingVertical = "FIXED";
tab.resize(tab.width, ROW_H);
tab.primaryAxisAlignItems = "MIN";
tab.paddingTop = 11;          // measured
underline.visible = true;      // present for every tab
if (!isActive) underline.fills = [];
```

**Verify numerically, not by eye.** Collect each label's absolute vertical centre and assert there is exactly one distinct value:

```js
const centres = [...new Set(labels.map((l) => l.centre))];
return { allAligned: centres.length === 1, centres };
```

In one real tab bar this exposed three different baselines (327 active, 333 inactive, 327 for the adjacent control) that all looked plausible at a glance.

## 12. Selected vs. unselected states

Do not blanket-apply one text style across a control group. Tabs, segmented controls and nav items have a *selected* treatment (semibold + primary text + visible underline) and an *unselected* one (regular + secondary text + hidden underline). Applying the strong style to all of them — easy to do in a bulk pass — makes every tab look active.

## 13. Reuse design system components — but verify each one renders

Component instances beat hand-built frames for dev handoff: they stay linked, they carry the real spec, and a developer recognises them. Search the project's library for every control you are about to build by hand (`button`, `badge`, `tab`, `link`, `input`, `table cell`, `tooltip`).

**But a library can contain components that do not work.** Always instantiate one, screenshot it, and inspect before committing to it. Real failures found in one library:

| Symptom | Cause | Action |
|---|---|---|
| Instance renders blank, though a TEXT child holds the right characters | the component's font is not installed locally | do not use it; hand-build and report the component as unusable |
| Control is a fixed width (e.g. 94px) regardless of label | old component built without hugging | unusable for a variable-width control |
| Brand colour inside the instance is the wrong green/blue | component predates the current brand token | override to the project's current brand token, or reject |

Use what fits, hand-build the rest, and **tell the user which components you used and which you rejected and why** — a stale component is a design system finding worth surfacing.

**A component can silently render nothing.** The most dangerous library defect is a component wired to a legacy text style whose font is not installed: the TEXT node exists, holds the right characters, reports `visible: true` and `opacity: 1`, and paints *nothing*. Detect it with `node.hasMissingFont`, never by reading the node tree.

Real example: `new_Button`'s Primary variants used `Body normal/Semibold` (SF Pro, installed) and rendered fine, while its Secondary variants used `SF Pro/Body Emphasized` (**SF Pro Text**, a different and uninstalled family) and came out as empty boxes. Repair on the instance by overriding `textStyleId` to the current style, and report the component as needing a fix at source — mixed text styles across variants of one component is a design system bug, not something to paper over on every screen.

**Component label sets are closed.** When a component carries its label in a *variant* rather than a text property (a status badge with `Type=Passed|Failed|Queued|…`), only those exact statuses can be expressed. If the design needs a status the system does not ship — "Healed", say — do not force the nearest wrong variant. Keep it hand-built, match it to the system's tokens, and report the gap.

**The project's current brand token wins over a component's baked-in colour.** When the team says "use X everywhere", apply it to instance overrides too, not just to the frames you build yourself.

## 14. Check font availability before trusting a text style

A design system can reference a font that is not installed locally (e.g. `SF Mono`). `listAvailableFontsAsync()` tells you. An imported text style still applies — the style carries the font reference — but any node you *create* must be given a loadable font before you set `characters`. Create text with a font you know is available, set the characters, then apply `textStyleId`.

Also: verify the style names. SF Pro exposes `Regular / Medium / Semibold / Bold / Light`; Inter uses `Semi Bold` (with a space), not `SemiBold`.

## 15. Don't default everything to body size

Dense product UIs run much smaller than marketing pages. One real screen's type census: **13px (5535 uses), 11px (1031), 12px (~1500)**. Buttons and badges were 12px/500, meta text 11px/400. Mapping all of it to a 13px body style makes every control look inflated. Map per measured size, and use the Semibold variants for control labels.
