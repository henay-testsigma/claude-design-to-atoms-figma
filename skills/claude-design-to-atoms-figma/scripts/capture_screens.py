#!/usr/bin/env python3
"""Render each screen headlessly: full-page PNG + computed styles per element.

Usage:
  capture_screens.py RUNDIR --out CAPTUREDIR [--viewport 1440x900] [--states states.json]

states.json (optional) drives extra captures of client-side views:
  [{"screen": "index.html", "name": "settings-modal",
    "actions": [{"click": "#open-settings"}, {"wait": 400}]}]
"""
import argparse
import json
import os
import re
import sys

PROBE = r"""
() => {
  const out = [];
  const MAX = 1500;
  const nodes = document.querySelectorAll('body, body *');
  for (let i = 0; i < nodes.length && out.length < MAX; i++) {
    const el = nodes[i];
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = getComputedStyle(el);
    const txt = (el.childNodes.length === 1 && el.firstChild.nodeType === 3)
      ? el.textContent.trim().slice(0, 80) : '';
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 160) : '',
      text: txt,
      x: Math.round(r.x), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
      color: s.color,
      backgroundColor: s.backgroundColor === 'rgba(0, 0, 0, 0)' ? '' : s.backgroundColor,
      backgroundImage: s.backgroundImage === 'none' ? '' : s.backgroundImage.slice(0, 200),
      borderColor: (parseFloat(s.borderTopWidth) > 0) ? s.borderTopColor : '',
      borderWidth: parseFloat(s.borderTopWidth) || 0,
      fontFamily: s.fontFamily,
      fontSize: s.fontSize,
      fontWeight: s.fontWeight,
      lineHeight: s.lineHeight,
      letterSpacing: s.letterSpacing,
      borderRadius: s.borderRadius === '0px' ? '' : s.borderRadius,
      boxShadow: s.boxShadow === 'none' ? '' : s.boxShadow,
      padding: s.padding,
      gap: s.gap && s.gap !== 'normal' ? s.gap : '',
      display: s.display,
      opacity: s.opacity,
    });
  }
  return { url: location.href, title: document.title,
           scrollHeight: document.documentElement.scrollHeight, elements: out };
}
"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "screen"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--viewport", default="1440x900")
    ap.add_argument("--states", help="JSON file describing extra interaction states")
    ap.add_argument("--full-page", action="store_true", default=True)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed. Run:\n  pip3 install playwright && "
              "python3 -m playwright install chromium", file=sys.stderr)
        return 2

    inv_path = os.path.join(args.run, "inventory.json")
    if not os.path.exists(inv_path):
        print("no inventory.json — run ingest_design.py first", file=sys.stderr)
        return 1
    inv = json.load(open(inv_path))
    src_dir = inv["src_dir"]
    os.makedirs(args.out, exist_ok=True)

    w, _, h = args.viewport.partition("x")
    viewport = {"width": int(w), "height": int(h or 900)}

    states = []
    if args.states and os.path.exists(args.states):
        loaded = json.load(open(args.states))
        # discover_states.py writes {screen, candidates, states, skipped};
        # a hand-written file may be a bare list of state objects.
        states = loaded["states"] if isinstance(loaded, dict) else loaded
        bad = [s for s in states if not isinstance(s, dict) or "screen" not in s]
        if bad:
            print("%d malformed state entries ignored (need {screen, name, actions})"
                  % len(bad), file=sys.stderr)
            states = [s for s in states if s not in bad]

    captured, failed = [], []
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as e:
                print("could not launch chromium: %s\nRun:\n  python3 -m playwright "
                      "install chromium" % e, file=sys.stderr)
                return 2
            ctx = browser.new_context(viewport=viewport, device_scale_factor=2)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            def capture(rel_file, name, actions=None):
                url = "file://" + os.path.join(src_dir, rel_file)
                page.goto(url, wait_until="load")
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(600)  # in-page Babel/React needs a beat
                for act in actions or []:
                    try:
                        if "role" in act and "name" in act:
                            page.get_by_role(act["role"], name=act["name"],
                                             exact=True).first.click(timeout=3000)
                        elif "click" in act and act["click"]:
                            page.click(act["click"], timeout=3000)
                        elif "fill" in act:
                            page.fill(act["fill"], act.get("value", ""), timeout=3000)
                        elif "hover" in act:
                            page.hover(act["hover"], timeout=3000)
                        elif "eval" in act:
                            page.evaluate(act["eval"])
                        elif "wait" in act:
                            page.wait_for_timeout(int(act["wait"]))
                    except Exception as e:
                        failed.append({"screen": name, "action": act, "error": str(e)})
                png = os.path.join(args.out, "%s.png" % name)
                page.screenshot(path=png, full_page=args.full_page)
                data = page.evaluate(PROBE)
                data["source_file"] = rel_file
                data["name"] = name
                data["viewport"] = viewport
                data["console_errors"] = errors[-10:]
                with open(os.path.join(args.out, "%s.computed.json" % name), "w") as fh:
                    json.dump(data, fh, indent=2)
                captured.append({"name": name, "file": rel_file, "png": png,
                                 "elements": len(data["elements"]),
                                 "scrollHeight": data["scrollHeight"]})
                print("captured %-28s %4d elements  %dpx tall" % (
                    name, len(data["elements"]), data["scrollHeight"]))

            for s in inv["screens"]:
                errors = []
                capture(s["file"], slug(s.get("title") or os.path.splitext(s["file"])[0]))
            for st in states:
                errors = []
                capture(st["screen"], slug(st["name"]), st.get("actions"))

            browser.close()
    except Exception as e:
        print("capture failed: %s" % e, file=sys.stderr)
        return 1

    with open(os.path.join(args.out, "index.json"), "w") as fh:
        json.dump({"captured": captured, "failed_actions": failed}, fh, indent=2)
    print("\n%d screens captured -> %s" % (len(captured), args.out))
    if failed:
        print("%d interaction steps failed (see index.json) — those states were captured "
              "without them" % len(failed))
    print("next: extract_tokens.py %s --out %s/source-tokens.json --merge-computed %s"
          % (args.run, args.run, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
