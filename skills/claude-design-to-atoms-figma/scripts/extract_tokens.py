#!/usr/bin/env python3
"""Extract the design's own tokens (colors, type, radii, spacing, shadows).

Usage:
  extract_tokens.py RUNDIR --out source-tokens.json [--merge-computed RUNDIR/capture]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

TEXT_EXT = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".json", ".svg"}
SKIP_DIRS = {"node_modules", ".git", "__MACOSX"}

NAMED = {  # only the few that actually show up in generated designs
    "white": "#FFFFFF", "black": "#000000", "transparent": None,
    "currentcolor": None, "inherit": None,
}

HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
RGB_RE = re.compile(r"rgba?\(\s*([^)]+?)\s*\)")
HSL_RE = re.compile(r"hsla?\(\s*([^)]+?)\s*\)")
OKLCH_RE = re.compile(r"oklch\(\s*([^)]+?)\s*\)")
VAR_DEF_RE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+)[;}]")
FONT_FAM_RE = re.compile(r"font-family\s*:\s*([^;{}]+)", re.I)
TW_FONT_RE = re.compile(r"font-\[(?:'|\")?([^\]'\"]+)(?:'|\")?\]")
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([0-9.]+)(px|rem|em|pt)", re.I)
LINE_H_RE = re.compile(r"line-height\s*:\s*([0-9.]+)(px|rem|em|%)?", re.I)
RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;{}]+)", re.I)
SHADOW_RE = re.compile(r"box-shadow\s*:\s*([^;{}]+)", re.I)
GRADIENT_RE = re.compile(r"(linear-gradient|radial-gradient|conic-gradient)\(([^;{}]*)\)", re.I)
SPACING_RE = re.compile(r"(?:padding|margin|gap|row-gap|column-gap)[a-z-]*\s*:\s*([^;{}]+)", re.I)
TW_ARB_RE = re.compile(r"(?:bg|text|border|from|via|to|fill|stroke|ring|shadow|decoration|outline)-\[([^\]]+)\]")


def norm_hex(raw):
    h = raw.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    elif len(h) == 4:
        h = "".join(c * 2 for c in h[:3])  # drop alpha nibble
    elif len(h) == 8:
        h = h[:6]
    if len(h) != 6:
        return None
    return "#" + h.upper()


def rgb_to_hex(parts):
    nums = re.split(r"[,\s/]+", parts.strip())
    vals = []
    for n in nums[:3]:
        n = n.strip()
        if not n:
            continue
        if n.endswith("%"):
            vals.append(round(float(n[:-1]) * 255 / 100))
        else:
            try:
                vals.append(round(float(n)))
            except ValueError:
                return None
    if len(vals) != 3:
        return None
    return "#" + "".join("%02X" % max(0, min(255, v)) for v in vals)


def hsl_to_hex(parts):
    nums = re.split(r"[,\s/]+", parts.strip())
    try:
        h = float(re.sub(r"deg|turn|rad", "", nums[0])) % 360
        s = float(nums[1].rstrip("%")) / 100.0
        l = float(nums[2].rstrip("%")) / 100.0
    except (ValueError, IndexError):
        return None
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
    seg = int(h // 60)
    table = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)]
    r, g, b = table[min(seg, 5)]
    return "#" + "".join("%02X" % round((v + m) * 255) for v in (r, g, b))


def colors_in(text):
    """Yield (hex, original_literal). Unresolvable forms yield (None, literal)."""
    for m in HEX_RE.finditer(text):
        h = norm_hex(m.group(1))
        if h:
            yield h, m.group(0)
    for m in RGB_RE.finditer(text):
        h = rgb_to_hex(m.group(1))
        yield h, m.group(0)
    for m in HSL_RE.finditer(text):
        h = hsl_to_hex(m.group(1))
        yield h, m.group(0)
    for m in OKLCH_RE.finditer(text):
        yield None, m.group(0)  # needs the computed capture to resolve


def px(value, base=16.0):
    v = value.strip().lower()
    m = re.match(r"^([0-9.]+)(px|rem|em|pt)?$", v)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "px"
    if unit == "px":
        return n
    if unit in ("rem", "em"):
        return n * base
    if unit == "pt":
        return n * 4 / 3
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--merge-computed", metavar="CAPTURE_DIR",
                    help="fold computed.json values from capture_screens.py into the result")
    args = ap.parse_args()

    src_dir = os.path.join(args.run, "src")
    if not os.path.isdir(src_dir):
        print("no src/ in %s — run ingest_design.py first" % args.run, file=sys.stderr)
        return 1

    colors = Counter()
    color_files = defaultdict(set)
    unresolved = Counter()
    css_vars = defaultdict(set)
    fonts = Counter()
    sizes = Counter()
    line_heights = Counter()
    radii = Counter()
    spacing = Counter()
    shadows = Counter()
    gradients = Counter()
    gradient_members = Counter()

    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = os.path.join(root, f)
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            rel = os.path.relpath(p, src_dir)
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue

            for hexv, lit in colors_in(text):
                if hexv:
                    colors[hexv] += 1
                    color_files[hexv].add(rel)
                else:
                    unresolved[lit] += 1
            for name, val in VAR_DEF_RE.findall(text):
                css_vars[name].add(val.strip())
            for fam in FONT_FAM_RE.findall(text):
                fonts[re.sub(r"\s+", " ", fam.strip().strip(";"))] += 1
            for fam in TW_FONT_RE.findall(text):
                fonts[fam.replace("_", " ").strip()] += 1
            for n, unit in FONT_SIZE_RE.findall(text):
                v = px(n + unit)
                if v:
                    sizes[round(v, 2)] += 1
            for n, unit in LINE_H_RE.findall(text):
                if not unit:
                    line_heights["%sx" % n] += 1
                elif unit == "%":
                    line_heights["%s%%" % n] += 1
                else:
                    v = px(n + unit)
                    if v:
                        line_heights[round(v, 2)] += 1
            for val in RADIUS_RE.findall(text):
                radii[re.sub(r"\s+", " ", val.strip())] += 1
            for val in SHADOW_RE.findall(text):
                shadows[re.sub(r"\s+", " ", val.strip())] += 1
            for kind, body in GRADIENT_RE.findall(text):
                gradients["%s(%s)" % (kind, re.sub(r"\s+", " ", body.strip()))] += 1
                for hexv, _ in colors_in(body):
                    if hexv:
                        gradient_members[hexv] += 1
            for val in SPACING_RE.findall(text):
                for tok in val.split():
                    v = px(tok)
                    if v is not None:
                        spacing[round(v, 2)] += 1
            for arb in TW_ARB_RE.findall(text):
                for hexv, _ in colors_in(arb):
                    if hexv:
                        colors[hexv] += 1
                        color_files[hexv].add(rel)

    computed_note = None
    if args.merge_computed:
        merged_colors, merged_type = Counter(), Counter()
        type_weights = {}
        cap = args.merge_computed
        n_files = 0
        for f in sorted(os.listdir(cap)) if os.path.isdir(cap) else []:
            if not f.endswith("computed.json"):
                continue
            n_files += 1
            data = json.load(open(os.path.join(cap, f)))
            for el in data.get("elements", []):
                for key in ("color", "backgroundColor", "borderColor"):
                    v = el.get(key)
                    if not v:
                        continue
                    for hexv, _ in colors_in(v):
                        if hexv:
                            merged_colors[hexv] += 1
                fs, lh = el.get("fontSize"), el.get("lineHeight")
                if fs:
                    s = px(str(fs))
                    if s:
                        sizes[round(s, 2)] += 1
                if el.get("fontFamily"):
                    fonts[el["fontFamily"]] += 1
                if fs and lh:
                    fam = (el.get("fontFamily") or "").split(",")[0].strip(" '\"")
                    merged_type["%s|%s/%s" % (fam, fs, lh)] += 1
                    if el.get("fontWeight"):
                        type_weights["%s|%s/%s" % (fam, fs, lh)] = el["fontWeight"]
                if el.get("borderRadius"):
                    radii[el["borderRadius"]] += 1
                if el.get("boxShadow") and el["boxShadow"] != "none":
                    shadows[el["boxShadow"]] += 1
        for h, c in merged_colors.items():
            colors[h] += c
            color_files[h].add("computed")
        computed_note = {"files": n_files, "type_pairs": merged_type.most_common(),
                         "type_weights": type_weights}

    out = {
        "colors": [
            {"hex": h, "count": c, "files": sorted(color_files[h])[:8]}
            for h, c in colors.most_common()
        ],
        "unresolved_color_literals": unresolved.most_common(),
        "css_variables": {k: sorted(v) for k, v in sorted(css_vars.items())},
        "font_families": fonts.most_common(),
        "font_sizes_px": sorted(sizes.items(), key=lambda kv: -kv[1]),
        "line_heights": [[str(k), v] for k, v in sorted(line_heights.items(), key=lambda kv: -kv[1])],
        "border_radii": radii.most_common(),
        "spacing_px": sorted(((k, v) for k, v in spacing.items() if k > 0),
                             key=lambda kv: -kv[1]),
        "box_shadows": shadows.most_common(),
        "gradients": gradients.most_common(),
        "gradient_member_colors": gradient_members.most_common(),
        "computed": computed_note,
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)

    print("%d distinct colors, %d css vars, %d font families, %d sizes, %d shadows, %d gradients"
          % (len(colors), len(css_vars), len(fonts), len(sizes), len(shadows), len(gradients)))
    if unresolved:
        print("%d color literals need the computed capture to resolve (oklch/var indirection)"
              % sum(unresolved.values()))
    if not colors and not computed_note:
        print("WARNING: no color literals found — this is likely a Tailwind-class design. "
              "Run capture_screens.py and re-run with --merge-computed.")
    print("tokens: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
