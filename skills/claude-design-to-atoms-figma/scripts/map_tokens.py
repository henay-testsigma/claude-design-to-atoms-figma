#!/usr/bin/env python3
"""Map extracted design values onto Figma design system tokens.

Usage:
  map_tokens.py --source source-tokens.json --system design-system.json \
                --out mapping.json --markdown MAPPING.md [--min-count 1]

Colors are matched by CIEDE2000 in CIELAB, with semantic name overrides applied
before distance (see references/token-mapping.md). Type is matched on
size + line-height + weight + family.
"""
import argparse
import json
import math
import re
import sys

# --- color math ---------------------------------------------------------------

def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_lab(rgb):
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t):
        return t ** (1.0 / 3) if t > 216.0 / 24389 else (24389.0 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1, lab2):
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    kL = kC = kH = 1.0
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cb = (C1 + C2) / 2.0
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7))) if Cb > 0 else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2.0
    else:
        hbp = (h1p + h2p - 360) / 2.0
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30))
         + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6))
         - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dTheta = 30 * math.exp(-(((hbp - 275) / 25.0) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7)) if Cbp > 0 else 0.0
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dTheta)) * Rc
    return math.sqrt(
        (dLp / (kL * Sl)) ** 2 + (dCp / (kC * Sc)) ** 2 + (dHp / (kH * Sh)) ** 2
        + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh))
    )


# --- semantic intent ----------------------------------------------------------

INTENT_WORDS = {
    "error": ["error", "danger", "destructive", "invalid", "fail", "red", "delete", "remove"],
    "warning": ["warning", "warn", "caution", "pending", "amber", "yellow", "orange", "hold"],
    "success": ["success", "valid", "passed", "pass", "complete", "positive", "ok", "green"],
    "primary": ["primary", "brand", "accent", "cta", "action"],
    "neutral": ["neutral", "gray", "grey", "muted", "subtle", "border", "divider",
                "placeholder", "disabled", "surface", "background", "bg"],
    "info": ["info", "informational", "note", "blue", "link"],
    "ai": ["ai", "magic", "auto", "copilot", "assistant", "generate", "sparkle"],
    "dark": ["dark", "night", "inverse", "inverted"],
}


def intent_of(names):
    """Guess semantic intent from the CSS var names / class names a color is used under."""
    blob = " ".join(names).lower()
    hits = []
    for intent, words in INTENT_WORDS.items():
        if any(re.search(r"\b%s" % re.escape(w), blob) for w in words):
            hits.append(intent)
    # Most specific first: a var named --color-error-bg is error, not neutral.
    for pref in ("error", "warning", "success", "ai", "info", "primary", "dark", "neutral"):
        if pref in hits:
            return pref
    return None


def style_intent(style_name):
    return intent_of([style_name.replace("/", " ").replace("-", " ")])


# --- system parsing -----------------------------------------------------------

def collect_system_colors(system):
    """Return [{name, hex, key, kind, id, lab, intent}] from paint styles + color variables."""
    out = []

    def add(name, hexv, key, kind, node_id=None, extra=None):
        if not hexv:
            return
        try:
            lab = srgb_to_lab(hex_to_rgb(hexv))
        except (ValueError, IndexError):
            return
        row = {"name": name, "hex": hexv.upper(), "key": key, "kind": kind,
               "id": node_id, "lab": lab, "intent": style_intent(name)}
        if extra:
            row.update(extra)
        out.append(row)

    for s in system.get("paintStyles", []):
        hexv = s.get("hex") or s.get("value")
        if s.get("paintType") and s["paintType"] != "SOLID":
            # gradients/images: keep them listed but unmatched by distance
            out.append({"name": s["name"], "hex": None, "key": s.get("key"),
                        "kind": "paintStyle:%s" % s["paintType"], "id": s.get("id"),
                        "lab": None, "intent": style_intent(s["name"])})
            continue
        add(s["name"], hexv, s.get("key"), "paintStyle", s.get("id"))

    for c in system.get("variableCollections", []):
        for v in c.get("variables", []):
            if v.get("resolvedType") != "COLOR":
                continue
            for mode, val in (v.get("valuesByMode") or {}).items():
                add("%s/%s" % (c.get("name", "vars"), v["name"]),
                    val if isinstance(val, str) else (val or {}).get("hex"),
                    v.get("key"), "variable", v.get("id"),
                    {"collection": c.get("name"), "mode": mode,
                     "variableName": v["name"]})
    return out


def collect_system_type(system):
    rows = []
    for s in system.get("textStyles", []):
        rows.append({
            "name": s["name"], "key": s.get("key"), "id": s.get("id"),
            "family": (s.get("fontName") or {}).get("family") or s.get("fontFamily"),
            "style": (s.get("fontName") or {}).get("style") or s.get("fontStyle"),
            "size": s.get("fontSize"),
            "lineHeight": s.get("lineHeightPx") or s.get("lineHeight"),
            "letterSpacing": s.get("letterSpacing"),
        })
    return rows


WEIGHT_OF_STYLE = {
    "thin": 100, "extralight": 200, "ultralight": 200, "light": 300,
    "regular": 400, "normal": 400, "book": 400, "medium": 500,
    "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800,
    "heavy": 800, "black": 900,
}


def weight_of(style):
    if not style:
        return 400
    s = re.sub(r"[^a-z]", "", str(style).lower())
    for k, v in WEIGHT_OF_STYLE.items():
        if k in s:
            return v
    return 400


def lh_px(v, size):
    """Normalize a line-height (px number, '1.5x', '150%') to px."""
    if v is None or size is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    m = re.match(r"^([0-9.]+)(x|%|px)?$", s)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    if unit == "%":
        return size * n / 100.0
    if unit == "x" or unit is None and n < 4:
        return size * n
    return n


# --- mapping ------------------------------------------------------------------

BANDS = [("exact", 0.0), ("close", 2.0), ("far", 10.0)]


def band_for(delta):
    for name, limit in BANDS:
        if delta <= limit + 1e-9:
            return name
    return "unmapped"


def map_colors(source, sys_colors, min_count):
    solid = [c for c in sys_colors if c["lab"]]
    grad_styles = [c["name"] for c in sys_colors
                   if c["kind"].startswith("paintStyle:GRADIENT")]
    # A color that only ever appears inside a gradient declaration is a stop,
    # not a fill — matching it to the nearest solid is always wrong.
    grad_only = {}
    for h, n in source.get("gradient_member_colors", []):
        grad_only[h] = n
    rows = []
    var_owner = {}
    for name, vals in (source.get("css_variables") or {}).items():
        for v in vals:
            for m in re.finditer(r"#[0-9a-fA-F]{3,8}", v):
                h = m.group(0).upper()
                if len(h) == 4:
                    h = "#" + "".join(c * 2 for c in h[1:])
                var_owner.setdefault(h[:7], []).append(name)

    for entry in source.get("colors", []):
        if entry["count"] < min_count:
            continue
        hexv = entry["hex"]
        try:
            lab = srgb_to_lab(hex_to_rgb(hexv))
        except (ValueError, IndexError):
            continue
        if grad_only.get(hexv, 0) >= entry["count"]:
            rows.append({
                "value": hexv, "count": entry["count"],
                "used_in": entry.get("files", [])[:5], "context_names": [],
                "intent": "gradient-stop", "token": None, "token_hex": None,
                "token_key": None, "token_kind": None, "token_id": None,
                "delta_e": None, "band": "gradient-stop",
                "reason": "gradient stop — map the whole gradient, not the stop",
                "alternatives": [{"token": g} for g in grad_styles[:4]],
            })
            continue
        context = var_owner.get(hexv, []) + entry.get("files", [])
        want = intent_of(context)
        scored = sorted(((ciede2000(lab, c["lab"]), c) for c in solid), key=lambda t: t[0])
        best_d, best = scored[0]
        chosen_reason = "nearest"
        if want:
            same = [(d, c) for d, c in scored if c["intent"] == want]
            # Only override if the semantic candidate is still visually plausible.
            if same and same[0][0] <= 12.0 and same[0][1]["name"] != best["name"]:
                best_d, best = same[0]
                chosen_reason = "semantic:%s" % want
        rows.append({
            "value": hexv, "count": entry["count"],
            "used_in": entry.get("files", [])[:5],
            "context_names": sorted(set(var_owner.get(hexv, [])))[:5],
            "intent": want,
            "token": best["name"], "token_hex": best["hex"], "token_key": best["key"],
            "token_kind": best["kind"], "token_id": best["id"],
            "delta_e": round(best_d, 2), "band": band_for(best_d),
            "reason": chosen_reason,
            "alternatives": [
                {"token": c["name"], "hex": c["hex"], "delta_e": round(d, 2)}
                for d, c in scored[1:4]
            ],
        })
    return rows


def map_type(source, sys_type):
    """Pair up the design's (size, line-height) combos with text styles."""
    sizes = [float(s) for s, _ in source.get("font_sizes_px", [])]
    counts = dict((float(s), c) for s, c in source.get("font_sizes_px", []))
    pairs = []
    computed = source.get("computed") or {}
    weights = (computed.get("type_weights") or {})
    for combo, n in (computed.get("type_pairs") or []):
        # "Inter|14px/20px" from the computed capture, or "14px/20px" without a family.
        fam, _, rest = combo.rpartition("|")
        m = re.match(r"^([0-9.]+)px/([0-9.]+)(px)?$", rest)
        if m:
            pairs.append((float(m.group(1)), float(m.group(2)), n,
                          fam or None, weights.get(combo)))
    if not pairs:
        pairs = [(sz, None, counts.get(sz, 1), None, None) for sz in sizes]

    src_families = [f for f, _ in source.get("font_families", [])]
    primary_family = None
    if src_families:
        primary_family = re.split(r",", src_families[0])[0].strip(" '\"")

    rows = []
    for size, lh, n, fam, weight in sorted(pairs, key=lambda t: -t[2]):
        # Per-element family beats the design's primary family: a 12px monospace
        # run must land on a Monospace style, not on Body small.
        want_fam = fam or primary_family
        best, best_score = None, None
        for st in sys_type:
            if not st["size"]:
                continue
            ds = abs(float(st["size"]) - size)
            st_lh = lh_px(st["lineHeight"], float(st["size"]))
            dl = abs(st_lh - lh) if (lh and st_lh) else 0.0
            fam_pen = 0.0
            if want_fam and st["family"]:
                a, b = want_fam.lower(), st["family"].lower()
                fam_pen = 0.0 if (a in b or b in a) else 8.0
            w_pen = 0.0
            if weight:
                try:
                    w_pen = min(abs(int(weight) - weight_of(st["style"])) / 100.0, 3.0)
                except (TypeError, ValueError):
                    w_pen = 0.0
            score = ds * 2 + dl + fam_pen + w_pen
            if best_score is None or score < best_score:
                best, best_score = st, score
        if not best:
            continue
        ds = abs(float(best["size"]) - size)
        fam_mismatch = bool(want_fam and best["family"]
                            and want_fam.lower() not in best["family"].lower()
                            and best["family"].lower() not in want_fam.lower())
        if fam_mismatch:
            band = "far"
        elif ds == 0 and best_score == 0:
            band = "exact"
        elif ds <= 1:
            band = "close"
        else:
            band = "far" if ds <= 4 else "unmapped"
        rows.append({
            "value": "%s%gpx%s" % ("%s " % fam if fam else "", size,
                                   "/%g" % lh if lh else ""),
            "count": n,
            "token": best["name"], "token_key": best["key"], "token_id": best["id"],
            "token_spec": "%s %s %g/%s" % (best["family"], best["style"], best["size"],
                                           lh_px(best["lineHeight"], float(best["size"]))),
            "delta_px": round(ds, 2), "band": band,
            "family_mismatch": fam_mismatch or None,
        })
    return rows


def map_numeric(source_items, sys_variables, kinds, label):
    """Map radii / spacing numbers onto FLOAT variables whose name suggests the kind."""
    cands = []
    for c in sys_variables:
        for v in c.get("variables", []):
            if v.get("resolvedType") != "FLOAT":
                continue
            name = "%s/%s" % (c.get("name", "vars"), v["name"])
            if not any(k in name.lower() for k in kinds):
                continue
            for _, val in (v.get("valuesByMode") or {}).items():
                if isinstance(val, (int, float)):
                    cands.append({"name": name, "key": v.get("key"),
                                  "id": v.get("id"), "value": float(val)})
                    break
    rows = []
    for raw, n in source_items:
        try:
            val = float(re.sub(r"[^0-9.]", "", str(raw)) or 0)
        except ValueError:
            continue
        if not cands:
            rows.append({"value": str(raw), "count": n, "token": None,
                         "band": "unmapped", "note": "no %s variables in the system" % label})
            continue
        best = min(cands, key=lambda c: abs(c["value"] - val))
        d = abs(best["value"] - val)
        rows.append({"value": str(raw), "count": n, "token": best["name"],
                     "token_key": best["key"], "token_id": best["id"],
                     "token_value": best["value"], "delta_px": round(d, 2),
                     "band": "exact" if d == 0 else ("close" if d <= 1 else
                            ("far" if d <= 4 else "unmapped"))})
    return rows


def md_table(rows, cols, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            cells.append("" if v is None else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown")
    ap.add_argument("--min-count", type=int, default=1)
    args = ap.parse_args()

    source = json.load(open(args.source))
    system = json.load(open(args.system))

    sys_colors = collect_system_colors(system)
    sys_type = collect_system_type(system)
    if not sys_colors:
        print("no colors found in design-system.json — re-run inspect_design_system.js "
              "and check that paintStyles/variableCollections are populated", file=sys.stderr)
        return 1

    colors = map_colors(source, sys_colors, args.min_count)
    types = map_type(source, sys_type)
    radii = map_numeric(source.get("border_radii", []),
                        system.get("variableCollections", []),
                        ["radius", "radii", "corner", "round"], "radius")
    spacing = map_numeric(source.get("spacing_px", []),
                          system.get("variableCollections", []),
                          ["space", "spacing", "gap", "padding", "size"], "spacing")

    effect_styles = [s["name"] for s in system.get("effectStyles", [])]
    shadows = [{"value": v, "count": n,
                "candidates": effect_styles[:6],
                "band": "review" if effect_styles else "unmapped"}
               for v, n in source.get("box_shadows", [])]
    gradients = [{"value": v, "count": n,
                  "candidates": [c["name"] for c in sys_colors
                                 if c["kind"].startswith("paintStyle:GRADIENT")][:6],
                  "band": "review"}
                 for v, n in source.get("gradients", [])]

    def tally(rows):
        t = {}
        for r in rows:
            t[r["band"]] = t.get(r["band"], 0) + 1
        return t

    mapping = {
        "colors": colors, "type": types, "radii": radii, "spacing": spacing,
        "shadows": shadows, "gradients": gradients,
        "summary": {
            "colors": tally(colors), "type": tally(types), "radii": tally(radii),
            "spacing": tally(spacing),
            "shadows": len(shadows), "gradients": len(gradients),
            "system_colors": len([c for c in sys_colors if c["lab"]]),
            "system_text_styles": len(sys_type),
            "system_effect_styles": len(effect_styles),
        },
    }
    with open(args.out, "w") as fh:
        json.dump(mapping, fh, indent=2)

    REVIEW = ("far", "unmapped", "gradient-stop")
    needs_review = ([r for r in colors if r["band"] in REVIEW]
                    + [r for r in types if r["band"] in REVIEW])

    if args.markdown:
        parts = ["# Token mapping ledger", "",
                 "Source: `%s`  ·  System: `%s`" % (args.source, args.system), "",
                 "## Summary", "",
                 "- Colors: %s" % mapping["summary"]["colors"],
                 "- Type: %s" % mapping["summary"]["type"],
                 "- Radii: %s" % mapping["summary"]["radii"],
                 "- Spacing: %s" % mapping["summary"]["spacing"],
                 "- Shadows needing a call: %d   Gradients: %d"
                 % (len(shadows), len(gradients)), "",
                 "**%d row(s) need review before building.**" % len(needs_review), ""]
        if needs_review:
            parts += ["## Needs review", "",
                      md_table(needs_review,
                               ["value", "count", "token", "delta_e", "delta_px", "band", "intent"],
                               ["Value", "Uses", "Proposed token", "ΔE", "Δpx", "Band", "Intent"]), ""]
        parts += ["## Colors", "",
                  md_table(colors, ["value", "count", "token", "token_hex", "delta_e",
                                    "band", "reason", "context_names"],
                           ["Design", "Uses", "DS token", "DS hex", "ΔE", "Band",
                            "Why", "Seen as"]), "",
                  "## Type", "",
                  md_table(types, ["value", "count", "token", "token_spec", "delta_px", "band"],
                           ["Design", "Uses", "Text style", "Style spec", "Δpx", "Band"]), "",
                  "## Radii", "",
                  md_table(radii, ["value", "count", "token", "token_value", "band"],
                           ["Design", "Uses", "Variable", "Value", "Band"]), "",
                  "## Spacing", "",
                  md_table(spacing, ["value", "count", "token", "token_value", "band"],
                           ["Design", "Uses", "Variable", "Value", "Band"]), "",
                  "## Shadows (pick an effect style per row)", "",
                  md_table(shadows, ["value", "count", "candidates"],
                           ["Design shadow", "Uses", "Effect styles available"]), "",
                  "## Gradients", "",
                  md_table(gradients, ["value", "count", "candidates"],
                           ["Design gradient", "Uses", "Gradient styles available"]), ""]
        with open(args.markdown, "w") as fh:
            fh.write("\n".join(parts))

    print("colors %s | type %s | radii %s | spacing %s"
          % (mapping["summary"]["colors"], mapping["summary"]["type"],
             mapping["summary"]["radii"], mapping["summary"]["spacing"]))
    print("%d row(s) need review%s" % (len(needs_review),
          " — show the ledger to the user before building" if needs_review else ""))
    print("mapping: %s%s" % (args.out, "  ledger: %s" % args.markdown if args.markdown else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
