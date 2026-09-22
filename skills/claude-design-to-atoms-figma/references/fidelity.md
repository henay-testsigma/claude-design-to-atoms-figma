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

**Minimum icon size is 16x16.** Never place a 12 or 14px icon — below 16 the Material Symbols geometry loses legibility and rows stop aligning to the 16px rhythm. Set both axes `FIXED` and `resize(16, 16)` (or larger), and sweep the screen at the end to catch any that slipped through.

Colour an instance by walking its descendants and setting `fillStyleId` on every node with fills — setting it on the instance alone does not always reach the vectors.

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

## 7. Check font availability before trusting a text style

A design system can reference a font that is not installed locally (e.g. `SF Mono`). `listAvailableFontsAsync()` tells you. An imported text style still applies — the style carries the font reference — but any node you *create* must be given a loadable font before you set `characters`. Create text with a font you know is available, set the characters, then apply `textStyleId`.

Also: verify the style names. SF Pro exposes `Regular / Medium / Semibold / Bold / Light`; Inter uses `Semi Bold` (with a space), not `SemiBold`.

## 8. Don't default everything to body size

Dense product UIs run much smaller than marketing pages. One real screen's type census: **13px (5535 uses), 11px (1031), 12px (~1500)**. Buttons and badges were 12px/500, meta text 11px/400. Mapping all of it to a 13px body style makes every control look inflated. Map per measured size, and use the Semibold variants for control labels.
