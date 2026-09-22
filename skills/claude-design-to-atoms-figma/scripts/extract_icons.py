#!/usr/bin/env python3
"""Extract inline SVG icons from the rendered design, for icons the library lacks.

Material Symbols (or whatever icon library the project uses) should always be
the first choice. When an icon genuinely has no equivalent, pull the real SVG
out of the render and insert it into Figma with figma.createNodeFromSvg().

Usage:
  extract_icons.py RUNDIR --out RUNDIR/icons [--screen index.html]
                   [--viewport 1440x900] [--max 80]

Writes one .svg per distinct icon plus icons.json describing where each was
used (nearest label, position, size) so you can match them to the right slot.
"""
import argparse
import hashlib
import json
import os
import re
import sys

PROBE = r"""
() => {
  const out = [];
  document.querySelectorAll('svg').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') return;

    // Nearest useful label: the icon's own aria-label, its button's text, or
    // the text of the closest labelled ancestor.
    let label = el.getAttribute('aria-label') || '';
    let n = el.parentElement, hops = 0;
    while (!label && n && hops < 4) {
      label = (n.getAttribute && n.getAttribute('aria-label')) ||
              (n.innerText || '').trim().split('\n')[0] || '';
      n = n.parentElement; hops++;
    }
    // Normalise the markup so identical icons dedupe.
    const clone = el.cloneNode(true);
    clone.removeAttribute('class');
    clone.removeAttribute('style');
    let markup = clone.outerHTML.replace(/\s+/g, ' ').trim();
    if (!/^<svg[^>]*\bxmlns=/.test(markup)) {
      markup = markup.replace(/^<svg/, '<svg xmlns="http://www.w3.org/2000/svg"');
    }
    out.push({
      label: (label || '').slice(0, 48),
      x: Math.round(r.x), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
      colour: s.color,
      markup,
    });
  });
  return out;
}
"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "icon"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--screen")
    ap.add_argument("--viewport", default="1440x900")
    ap.add_argument("--max", type=int, default=80)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed. Run:\n  pip3 install playwright && "
              "python3 -m playwright install chromium", file=sys.stderr)
        return 2

    inv_path = os.path.join(args.run, "inventory.json")
    if not os.path.exists(inv_path):
        print("no inventory.json - run ingest_design.py first", file=sys.stderr)
        return 1
    inv = json.load(open(inv_path))
    screen = args.screen or inv.get("entry_point")
    url = "file://" + os.path.join(inv["src_dir"], screen)

    w, _, h = args.viewport.partition("x")
    os.makedirs(args.out, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(
            viewport={"width": int(w), "height": int(h or 900)}).new_page()
        page.goto(url, wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(1200)          # bundled artifacts self-unpack
        found = page.evaluate(PROBE)
        browser.close()

    seen, records = {}, []
    for item in found:
        digest = hashlib.md5(item["markup"].encode()).hexdigest()[:10]
        if digest in seen:
            seen[digest]["uses"] += 1
            if item["label"] and item["label"] not in seen[digest]["labels"]:
                seen[digest]["labels"].append(item["label"])
            continue
        if len(records) >= args.max:
            continue
        name = "%s-%s" % (slug(item["label"]), digest)
        path = os.path.join(args.out, name + ".svg")
        with open(path, "w") as fh:
            fh.write(item["markup"])
        rec = {"name": name, "file": path, "labels": [item["label"]] if item["label"] else [],
               "w": item["w"], "h": item["h"], "colour": item["colour"],
               "x": item["x"], "y": item["y"], "uses": 1, "hash": digest}
        seen[digest] = rec
        records.append(rec)

    with open(os.path.join(args.out, "icons.json"), "w") as fh:
        json.dump({"screen": screen, "icons": records}, fh, indent=2)

    print("%d svg elements found, %d distinct written to %s"
          % (len(found), len(records), args.out))
    for r in sorted(records, key=lambda r: -r["uses"])[:15]:
        print("  %-42s %2dx%-2d  x%d  %s"
              % (r["name"][:42], r["w"], r["h"], r["uses"],
                 (r["labels"][0] if r["labels"] else "")[:24]))
    print("\nInsert into Figma with figma.createNodeFromSvg(<file contents>), then")
    print("resize to >=16px and set fillStyleId on the vector children.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
