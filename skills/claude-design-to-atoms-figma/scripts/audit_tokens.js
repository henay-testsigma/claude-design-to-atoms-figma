// Token coverage audit. Paste as the `use_figma` script and set ROOT_ID to the
// imported section/frame. Returns every value NOT bound to a variable or style.
// Target: zero rows, minus the ones the user signed off as unmapped.

const ROOT_ID = "PASTE_SECTION_OR_FRAME_ID";

const root = await figma.getNodeByIdAsync(ROOT_ID);
if (!root) throw new Error("node " + ROOT_ID + " not found — is it on another page?");

const hex = (c) => {
  const to = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255)
    .toString(16).padStart(2, "0").toUpperCase();
  return "#" + to(c.r) + to(c.g) + to(c.b);
};

const bound = (node, prop) => {
  const b = node.boundVariables || {};
  const v = b[prop];
  return Array.isArray(v) ? v.length > 0 : !!v;
};

const findings = { fills: [], strokes: [], text: [], radius: [], effects: [] };
let checked = 0, tokenized = 0;

// Inside an instance, values are governed by the main component — flag those
// separately so they are not counted against this import.
const inInstance = (n) => {
  for (let p = n.parent; p; p = p.parent) if (p.type === "INSTANCE") return true;
  return false;
};

for (const node of root.findAll(() => true)) {
  const base = { id: node.id, name: node.name, type: node.type,
                 governedByComponent: inInstance(node) };

  if ("fills" in node && Array.isArray(node.fills)) {
    node.fills.forEach((f, i) => {
      if (f.visible === false) return;
      checked++;
      const isBound = !!(f.boundVariables && f.boundVariables.color);
      const styled = node.fillStyleId && node.fillStyleId !== figma.mixed;
      if (isBound || styled) { tokenized++; return; }
      findings.fills.push(Object.assign({}, base, {
        index: i, paintType: f.type,
        value: f.type === "SOLID" ? hex(f.color) : f.type,
      }));
    });
  }

  if ("strokes" in node && Array.isArray(node.strokes)) {
    node.strokes.forEach((s, i) => {
      if (s.visible === false) return;
      checked++;
      const isBound = !!(s.boundVariables && s.boundVariables.color);
      const styled = node.strokeStyleId && node.strokeStyleId !== figma.mixed;
      if (isBound || styled) { tokenized++; return; }
      findings.strokes.push(Object.assign({}, base, {
        index: i, value: s.type === "SOLID" ? hex(s.color) : s.type }));
    });
  }

  if (node.type === "TEXT") {
    checked++;
    if (node.textStyleId && node.textStyleId !== figma.mixed) tokenized++;
    else findings.text.push(Object.assign({}, base, {
      chars: (node.characters || "").slice(0, 40),
      fontName: node.fontName === figma.mixed ? "MIXED" : node.fontName,
      fontSize: node.fontSize === figma.mixed ? "MIXED" : node.fontSize,
      mixed: node.textStyleId === figma.mixed,
    }));
  }

  if ("cornerRadius" in node && node.cornerRadius !== 0) {
    checked++;
    if (bound(node, "topLeftRadius") || bound(node, "bottomLeftRadius")) tokenized++;
    else findings.radius.push(Object.assign({}, base, {
      value: node.cornerRadius === figma.mixed ? "MIXED" : node.cornerRadius }));
  }

  if ("effects" in node && Array.isArray(node.effects) && node.effects.length) {
    checked++;
    if (node.effectStyleId) tokenized++;
    else findings.effects.push(Object.assign({}, base, {
      value: node.effects.map((e) => e.type).join(",") }));
  }
}

const own = (arr) => arr.filter((r) => !r.governedByComponent);
const counts = {
  fills: own(findings.fills).length, strokes: own(findings.strokes).length,
  text: own(findings.text).length, radius: own(findings.radius).length,
  effects: own(findings.effects).length,
};
const untokenizedOwn = Object.values(counts).reduce((a, b) => a + b, 0);

return {
  root: { id: root.id, name: root.name },
  checked, tokenized,
  coverage: checked ? Math.round((tokenized / checked) * 1000) / 10 + "%" : "n/a",
  untokenized_own_nodes: untokenizedOwn,
  untokenized_inside_instances:
    Object.values(findings).reduce((n, a) => n + a.length, 0) - untokenizedOwn,
  counts,
  // Trimmed so the return stays readable; re-run per screen for the full list.
  findings: {
    fills: own(findings.fills).slice(0, 40),
    strokes: own(findings.strokes).slice(0, 40),
    text: own(findings.text).slice(0, 40),
    radius: own(findings.radius).slice(0, 20),
    effects: own(findings.effects).slice(0, 20),
  },
};
