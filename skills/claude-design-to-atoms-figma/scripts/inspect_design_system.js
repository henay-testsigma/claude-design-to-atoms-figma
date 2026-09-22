// Read the design system out of a Figma file. Paste as the `use_figma` script
// (pass skillNames: "figma-use,claude-design-to-atoms-figma"). Save the result
// verbatim to $RUN/design-system.json — map_tokens.py reads this shape.
//
// RUN THIS AGAINST THE FILE THAT OWNS THE DESIGN SYSTEM, not the file you are
// drawing screens into. The local* APIs see only the current file, so running it
// against a file that merely LINKS the library returns an empty/partial system.
// The `key` values it returns are what importStyleByKeyAsync /
// importVariableByKeyAsync / importComponentSetByKeyAsync need in the target
// file; keys are stable across files, ids are not. Keys only import if the
// library is published. Also cross-check with search_design_system
// (entity:"variable"/"style"), which does see remote libraries.

const hex = (c) => {
  const to = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255)
    .toString(16).padStart(2, "0").toUpperCase();
  return "#" + to(c.r) + to(c.g) + to(c.b);
};

const paintOf = (p) => {
  if (!p) return null;
  if (p.type === "SOLID") {
    return { paintType: "SOLID", hex: hex(p.color),
             opacity: p.opacity === undefined ? 1 : p.opacity };
  }
  if (p.type.startsWith("GRADIENT")) {
    return { paintType: p.type,
             stops: (p.gradientStops || []).map((s) => ({
               hex: hex(s.color), a: s.color.a, pos: Math.round(s.position * 100) / 100 })) };
  }
  return { paintType: p.type };
};

const [paintStyles, textStyles, effectStyles, collections] = await Promise.all([
  figma.getLocalPaintStylesAsync(),
  figma.getLocalTextStylesAsync(),
  figma.getLocalEffectStylesAsync(),
  figma.variables.getLocalVariableCollectionsAsync(),
]);

const paints = paintStyles.map((s) => {
  const p = paintOf((s.paints || [])[0]);
  return Object.assign({ name: s.name, id: s.id, key: s.key, remote: s.remote,
                         paintCount: (s.paints || []).length }, p || {});
});

const texts = textStyles.map((s) => ({
  name: s.name, id: s.id, key: s.key, remote: s.remote,
  fontName: s.fontName, fontSize: s.fontSize,
  lineHeight: s.lineHeight,
  lineHeightPx: s.lineHeight && s.lineHeight.unit === "PIXELS" ? s.lineHeight.value
    : (s.lineHeight && s.lineHeight.unit === "PERCENT"
        ? Math.round(s.fontSize * s.lineHeight.value) / 100 : null),
  letterSpacing: s.letterSpacing, textCase: s.textCase,
  textDecoration: s.textDecoration,
}));

const effects = effectStyles.map((s) => ({
  name: s.name, id: s.id, key: s.key, remote: s.remote,
  effects: (s.effects || []).map((e) => ({
    type: e.type,
    color: e.color ? hex(e.color) : null,
    alpha: e.color ? Math.round(e.color.a * 100) / 100 : null,
    offset: e.offset || null, radius: e.radius, spread: e.spread,
  })),
}));

const variableCollections = [];
for (const c of collections) {
  const vars = await Promise.all(
    c.variableIds.map((id) => figma.variables.getVariableByIdAsync(id))
  );
  variableCollections.push({
    name: c.name, id: c.id, key: c.key, remote: c.remote,
    modes: c.modes.map((m) => ({ modeId: m.modeId, name: m.name })),
    defaultModeId: c.defaultModeId,
    variables: vars.filter(Boolean).map((v) => {
      const valuesByMode = {};
      for (const [modeId, val] of Object.entries(v.valuesByMode || {})) {
        const mode = c.modes.find((m) => m.modeId === modeId);
        const label = mode ? mode.name : modeId;
        if (val && typeof val === "object" && val.type === "VARIABLE_ALIAS") {
          valuesByMode[label] = { alias: val.id };
        } else if (v.resolvedType === "COLOR" && val && typeof val === "object") {
          valuesByMode[label] = hex(val);
        } else {
          valuesByMode[label] = val;
        }
      }
      return { name: v.name, id: v.id, key: v.key, resolvedType: v.resolvedType,
               scopes: v.scopes, valuesByMode };
    }),
  });
}

// Component sets + standalone components, so screen building can import by key.
const sets = figma.root.findAllWithCriteria({ types: ["COMPONENT_SET"] })
  .map((n) => ({ name: n.name, id: n.id, key: n.key, type: "COMPONENT_SET",
                 variants: n.children.map((c) => c.name).slice(0, 40) }));
const setIds = new Set(sets.map((s) => s.id));
const singles = figma.root.findAllWithCriteria({ types: ["COMPONENT"] })
  .filter((n) => !(n.parent && setIds.has(n.parent.id)))
  .map((n) => ({ name: n.name, id: n.id, key: n.key, type: "COMPONENT" }));

return {
  fileName: figma.root.name,
  pages: figma.root.children.map((p) => ({ name: p.name, id: p.id })),
  paintStyles: paints,
  textStyles: texts,
  effectStyles: effects,
  variableCollections,
  components: sets.concat(singles),
  counts: { paintStyles: paints.length, textStyles: texts.length,
            effectStyles: effects.length,
            variables: variableCollections.reduce((n, c) => n + c.variables.length, 0),
            components: sets.length + singles.length },
  warning: "Local APIs only — this is the system owned BY this file. If it came back near-empty, "
         + "you ran it against a file that only links the library; re-run against the library's "
         + "own fileKey. Cross-check with search_design_system before concluding a token is missing.",
};
