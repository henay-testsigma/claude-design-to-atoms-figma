# Token mapping rules

`map_tokens.py` proposes; you decide. These rules cover the cases where nearest-color is the wrong answer.

## 1. Semantics beat distance

A color's *job* in the UI outranks its hex proximity. The script already applies this when the CSS variable name or class name carries intent (`--color-error-bg`, `.badge-warning`, `bg-danger-500`), but it only sees names — you see the screenshot.

| If the value is used for | Map to | Even when the nearest hex is |
|---|---|---|
| Destructive buttons, invalid inputs, failure badges | Error ramp | any other red-ish or neutral |
| "Pending", "on hold", caution banners | Warning ramp | Error (reds and ambers are close in Lab) |
| Passing tests, success toasts, confirmations | the success/positive ramp (often the Primary green in a green-branded system) | Primary — check which the system intends |
| Borders, dividers, disabled text, placeholder text, page/card backgrounds | Neutral ramp | the brand ramp's light tints |
| Primary CTAs, active nav, selected state, focus rings | Primary ramp | Neutral or Secondary |
| AI actions, autoheal, generated content | the AI gradient styles | any solid |
| Section headers / chrome separated from content | a Section token if the system has one | Neutral |

When a ramp has two plausible steps (e.g. 400 vs 500), pick by **role consistency across screens**, not per-instance ΔE. One step per role, applied everywhere.

## 2. Ramp steps: match lightness order, not just distance

Designs generated from scratch rarely use the system's exact ramp. If the design uses 4 greys and the system has 10, map by **rank**: sort the design's greys by lightness and the system's Neutral ramp by lightness, then assign in order, preserving contrast relationships. Do not let two distinct design greys collapse onto the same token if they sit next to each other in the UI (a card on a page background) — that flattens the design. Keep at least one step of separation.

## 3. Type

Match on size first, then line-height, then weight, then family. The script scores `2·Δsize + Δline-height + family penalty`.

Fallback order when there is no clean match:

1. **Exact size + line-height** → use that style.
2. **Exact size, different line-height** → use the style, accept its line-height. The system's vertical rhythm should win over the design's.
3. **Off by ≤1px** → use the nearest style. Never create a new text style to preserve a 1px difference.
4. **Off by >4px with no style in range** → ask. Either the design invented a size the system doesn't carry (use the closest and note it), or this is a genuine gap in the system (worth telling the user).
5. **Weight mismatch within a family** → if the system exposes weight as a variant/nested style, use it; otherwise take the closest weight and flag it.

Headings usually map to the Title ramp, body copy to Body normal/small, code and IDs to Monospace. Labels, captions and helper text almost always belong to the smallest body style rather than a scaled-down title.

## 4. Elevation and dark mode

Systems that define elevation as **overlay percentages** (00dp / 01dp / 02dp … each with an overlay %) do not want your CSS `box-shadow` translated literally. Map instead by *elevation intent*:

| Design shadow | Elevation token |
|---|---|
| none / flat on background | 00dp |
| hairline card lift (`0 1px 2px`) | 01dp–02dp |
| resting card (`0 1px 3px`, `0 2px 4px`) | 02dp–04dp |
| dropdown, popover, tooltip | 06dp–08dp |
| modal, dialog, sheet | 12dp–16dp |
| nav drawer over content, toast | 16dp–24dp |

In dark mode, elevation is expressed as a **lighter surface**, not a darker shadow. If the design is dark-themed, map surfaces to the Dark Mode ramp by elevation step and only then add the effect style. Never pair a dark surface with a black drop shadow — that is a light-mode idiom.

## 5. Gradients, images, and things with no token

- Gradients: if the system publishes gradient paint styles (common for AI/brand treatments), use the style. If not, keep the gradient as a local paint and list it as unmapped — do not fake it with the nearest solid.
- Images/photos: not tokens. They come in via the `generate_figma_design` capture's `imageHash`.
- Overlay scrims (`rgba(0,0,0,0.5)`): map to the system's shades/overlay token if one exists, otherwise keep the alpha and flag it.
- Alpha variants of a solid (`#00000014`): the extractor drops alpha to match hue. If the design's intent is "8% black", that is an overlay, not a color — handle it as a scrim.

## 6. Browser defaults are not design intent

The computed capture reports what the browser rendered, including values the design never specified. These show up in the ledger and must be handled by role, not accepted literally:

| Symptom in the ledger | What it actually is |
|---|---|
| `#0000EE` / `#551A8B` | unstyled `<a>` default link/visited blue — map to the system's link or Primary token |
| `16px/24` or `16px/normal` with a high use count | unstyled text inheriting the UA default — decide the real style from the screenshot, usually Body normal |
| `#000000` on text with no `color` rule | UA default black — almost always the Neutral ramp's darkest step, not Shades/100 |
| `rgba(0,0,0,0)` backgrounds | transparent, not a color. Ignore |
| A font family you never saw in the CSS | UA fallback because the webfont did not load in headless. Use the family the source declares |

If a value appears *only* in the computed pass and not in the static pass, suspect a browser default before treating it as a design decision.

## 7. Recording decisions

`mapping.json` is the contract. Once the user approves it:

- Apply it **mechanically** for every screen. Do not re-decide a color because it looks slightly off on one screen — fix the mapping once, re-apply everywhere.
- Keep the file across re-runs so the same design value always lands on the same token.
- Anything the user explicitly approved as unmapped goes in an `approved_unmapped` array in `mapping.json`, with the reason. The Phase 7 audit subtracts exactly that list and nothing else.
