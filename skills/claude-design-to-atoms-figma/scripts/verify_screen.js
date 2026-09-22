// Automated screen verification. Paste as the `use_figma` script with ROOT_ID set
// to a built screen frame. Returns a defect list, most severe first.
//
// Run this after EVERY screen and fix everything it reports BEFORE showing the
// user. Every check here exists because a real review caught the defect by eye.

const ROOT_ID = "PASTE_SCREEN_FRAME_ID";
const MIN_ICON = 16;

const root = await figma.getNodeByIdAsync(ROOT_ID);
if (!root) throw new Error("node " + ROOT_ID + " not found (wrong page?)");

const defects = [];
const add = (check, severity, node, detail) =>
  defects.push({ check, severity, node: node ? node.name : "-",
                 id: node ? node.id : null, detail });

const inInstance = (n) => {
  for (let p = n.parent; p; p = p.parent) if (p.type === "INSTANCE") return true;
  return false;
};
const isIcon = (n) => n.name && n.name.indexOf("Icon / ") === 0;
const box = (n) => n.absoluteBoundingBox;

// Pictographic emoji, plus symbol glyphs commonly misused as icons.
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u;
const GLYPH_ICON = /^[←-⇿⌀-⏿■-◿⤀-⧿⬀-⯿·•›‹«»]+$/;

let checked = 0, tokenized = 0;

for (const n of root.findAll(() => true)) {
  const inInst = inInstance(n);

  // --- tokenisation ------------------------------------------------------
  if ("fills" in n && Array.isArray(n.fills)) {
    for (const f of n.fills) {
      if (f.visible === false || inInst) continue;   // instance internals are the library's
      checked++;
      if (n.fillStyleId && n.fillStyleId !== figma.mixed) { tokenized++; continue; }
      // A layout container with an unstyled opaque fill is almost always the
      // default white that createAutoLayout/createFrame applies.
      if (n.type === "FRAME" && "layoutMode" in n && n.layoutMode !== "NONE") {
        add("stray-container-fill", "high", n,
            "layout container has an unstyled fill; set fills = [] or apply a style");
      } else {
        add("untokenised-fill", "high", n, "fill not bound to a style");
      }
    }
  }
  if ("strokes" in n && Array.isArray(n.strokes)) {
    for (const s of n.strokes) {
      if (s.visible === false || inInst) continue;
      checked++;
      if (n.strokeStyleId && n.strokeStyleId !== figma.mixed) tokenized++;
      else if (!inInst) add("untokenised-stroke", "high", n, "stroke not bound to a style");
    }
  }
  if ("effects" in n && Array.isArray(n.effects) && n.effects.length && !inInst) {
    checked++;
    if (n.effectStyleId) tokenized++;
    else if (!inInst) add("untokenised-effect", "medium", n, "effect not bound to a style");
  }

  // --- text --------------------------------------------------------------
  if (n.type === "TEXT" && !inInst) {
    checked++;
    if (n.textStyleId && n.textStyleId !== figma.mixed) tokenized++;
    else if (!inInst) add("untokenised-text", "high", n,
      "no text style: \"" + (n.characters || "").slice(0, 24) + "\"");

    const chars = (n.characters || "").trim();
    if (EMOJI.test(chars)) {
      add("emoji-in-text", "high", n, "emoji must be an icon component: " + chars.slice(0, 12));
    } else if (chars.length <= 3 && GLYPH_ICON.test(chars)) {
      add("glyph-used-as-icon", "high", n,
          "\"" + chars + "\" looks like an icon drawn as text; use a component instance");
    }
    if (n.height === 0 || n.width === 0) {
      add("zero-size-text", "high", n, "text collapsed to zero size");
    }
  }

  // A missing font renders text INVISIBLE with no error anywhere. This fires
  // inside instances too: a library component can be wired to a legacy style
  // whose font is not installed, and the label silently disappears.
  if (n.type === "TEXT" && n.hasMissingFont) {
    const fam = n.fontName && n.fontName !== figma.mixed
      ? n.fontName.family + " " + n.fontName.style : "MIXED";
    add("missing-font-invisible-text", "high", n,
        "\"" + (n.characters || "").slice(0, 20) + "\" uses " + fam +
        " which is not installed - it will not render");
  }

  // --- icons -------------------------------------------------------------
  if (isIcon(n) && (n.width < MIN_ICON || n.height < MIN_ICON)) {
    add("icon-below-minimum", "medium", n,
        Math.round(n.width) + "x" + Math.round(n.height) + " < " + MIN_ICON);
  }
  if (isIcon(n) && n.type === "FRAME" && !inInst) {
    add("icon-placeholder", "high", n, "icon is a plain frame, not a component instance");
  }

  // --- clipping ----------------------------------------------------------
  // Clipping is legitimate when the frame exists to truncate a label; flag it
  // only where it would silently crop a child's shadow.
  if ("clipsContent" in n && n.clipsContent && n.id !== root.id && n.type === "FRAME") {
    const truncates = n.findAll && n.findAll((c) =>
      c.type === "TEXT" && c.textTruncation === "ENDING").length > 0;
    if (!truncates) add("inner-frame-clips", "medium", n,
      "clipsContent crops child shadows; set false");
  }

  // --- overflow ----------------------------------------------------------
  // Skip instance internals: a 1px overlap inside a library component is the
  // library's business and cannot be fixed from the consuming file.
  if (!inInst && "layoutMode" in n && n.layoutMode === "HORIZONTAL" && box(n)) {
    const pb = box(n);
    const innerR = pb.x + n.width - (n.paddingRight || 0);
    const innerL = pb.x + (n.paddingLeft || 0);
    for (const c of n.children) {
      if (!box(c) || c.visible === false) continue;
      if (box(c).x + c.width > innerR + 0.5) {
        add("child-overflows-parent", "high", c,
            "extends " + Math.round(box(c).x + c.width - innerR) +
            "px past \"" + n.name + "\" (a FILL spacer cannot shrink)");
      }
      if (box(c).x < innerL - 0.5) {
        add("child-overflows-parent", "high", c, "starts left of \"" + n.name + "\" padding");
      }
    }
  }
}

// --- baseline alignment within control rows -------------------------------
for (const rowNode of root.findAll((n) =>
      "layoutMode" in n && n.layoutMode === "HORIZONTAL" && n.children.length >= 3)) {
  const centres = [];
  for (const c of rowNode.children) {
    if (c.visible === false || c.name === "Spacer") continue;
    const t = c.type === "TEXT" ? c
      : (c.findOne ? c.findOne((x) => x.type === "TEXT" && x.visible !== false) : null);
    if (t && box(t)) centres.push({ label: (t.characters || "").slice(0, 14),
                                    centre: Math.round(box(t).y + t.height / 2) });
  }
  const distinct = [...new Set(centres.map((c) => c.centre))];
  if (centres.length >= 3 && distinct.length > 1 &&
      Math.max(...distinct) - Math.min(...distinct) > 1) {
    add("labels-not-on-one-baseline", "medium", rowNode,
        "label centres " + distinct.join("/") + " — decorations may be shifting labels");
  }
}

const order = { high: 0, medium: 1, low: 2 };
defects.sort((a, b) => order[a.severity] - order[b.severity]);
const counts = {};
for (const d of defects) counts[d.check] = (counts[d.check] || 0) + 1;

return {
  root: root.name,
  coverage: checked ? Math.round((tokenized / checked) * 1000) / 10 + "%" : "n/a",
  checked, tokenized,
  defectCount: defects.length,
  bySeverity: {
    high: defects.filter((d) => d.severity === "high").length,
    medium: defects.filter((d) => d.severity === "medium").length,
  },
  counts,
  defects: defects.slice(0, 60),
  PASS: defects.filter((d) => d.severity === "high").length === 0,
};
