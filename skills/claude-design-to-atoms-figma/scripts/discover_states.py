#!/usr/bin/env python3
"""Discover interaction states in a rendered design (tabs, toggles, modals, expanders).

Static markup analysis cannot see these in a bundled/SPA design — the DOM only
exists after JS runs. This renders the page, enumerates interactive elements,
optionally clicks each one in a fresh page, and keeps the ones that actually
change the view (by DOM signature). Output is a states.json that
capture_screens.py can consume directly.

Usage:
  discover_states.py RUNDIR --out states.json [--probe] [--max-probes 40]
                     [--viewport 1440x900] [--screen index.html]
"""
import argparse
import hashlib
import json
import os
import re
import sys

ENUMERATE = r"""
() => {
  const SEL = 'button,[role="tab"],[role="button"],[role="menuitem"],[role="switch"],' +
              'a[href],select,summary,details,[aria-expanded],[aria-haspopup],' +
              '[data-state],input[type="checkbox"],input[type="radio"],label';
  const out = [];
  const seen = new Set();
  document.querySelectorAll(SEL).forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return;                    // invisible
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') return;
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || '')
      .trim().replace(/\s+/g, ' ').slice(0, 60);
    if (!label) return;
    // A stable-ish selector: prefer id, then a text-scoped role query.
    let sel = null;
    if (el.id && !/^[0-9]/.test(el.id) && !/:/.test(el.id)) sel = '#' + el.id;
    const role = el.getAttribute('role') ||
      (el.tagName === 'BUTTON' ? 'button' : el.tagName === 'A' ? 'link' : el.tagName.toLowerCase());
    const key = role + '|' + label;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({
      label, role, tag: el.tagName.toLowerCase(), selector: sel,
      ariaExpanded: el.getAttribute('aria-expanded'),
      ariaSelected: el.getAttribute('aria-selected'),
      dataState: el.getAttribute('data-state'),
      x: Math.round(r.x), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
    });
  });
  return out;
}
"""

# A coarse fingerprint of the rendered view: visible text + box geometry.
SIGNATURE = r"""
() => {
  const parts = [];
  document.querySelectorAll('body *').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const t = (el.childNodes.length === 1 && el.firstChild.nodeType === 3)
      ? el.textContent.trim().slice(0, 40) : '';
    parts.push(el.tagName + Math.round(r.x) + ',' + Math.round(r.y) + ',' +
               Math.round(r.width) + ',' + Math.round(r.height) + t);
  });
  return parts.join('|');
}
"""

# Labels that navigate away, download, or mutate rather than reveal a view.
SKIP = re.compile(
    r"^(download|export|save|delete|remove|submit|sign out|log ?out|print|share|"
    r"copy|refresh|reload|close|cancel)\b", re.I)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "state"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--probe", action="store_true",
                    help="click each candidate in a fresh page and keep the ones that change the view")
    ap.add_argument("--max-probes", type=int, default=40)
    ap.add_argument("--viewport", default="1440x900")
    ap.add_argument("--screen", help="which html file to probe (default: the entry point)")
    ap.add_argument("--settle", type=int, default=700, help="ms to wait after each click")
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
    screen = args.screen or inv.get("entry_point")
    url = "file://" + os.path.join(inv["src_dir"], screen)

    w, _, h = args.viewport.partition("x")
    viewport = {"width": int(w), "height": int(h or 900)}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=viewport)
        page = ctx.new_page()

        def load():
            page.goto(url, wait_until="load")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(1200)  # bundled artifacts self-unpack

        load()
        candidates = page.evaluate(ENUMERATE)
        base_sig = hashlib.md5(page.evaluate(SIGNATURE).encode()).hexdigest()
        print("%d interactive elements found" % len(candidates))

        states, skipped = [], []
        if args.probe:
            probeable = [c for c in candidates if not SKIP.match(c["label"])]
            print("probing %d of them (cap %d)…" %
                  (min(len(probeable), args.max_probes), args.max_probes))
            seen_sigs = {base_sig: "default"}
            for c in probeable[:args.max_probes]:
                try:
                    load()
                    # role+name is far more robust than a CSS path in a bundled app
                    if c["selector"]:
                        page.click(c["selector"], timeout=3000)
                    else:
                        page.get_by_role(c["role"], name=c["label"], exact=True) \
                            .first.click(timeout=3000)
                    page.wait_for_timeout(args.settle)
                    sig = hashlib.md5(page.evaluate(SIGNATURE).encode()).hexdigest()
                except Exception as e:
                    skipped.append({"label": c["label"], "why": str(e).split("\n")[0][:120]})
                    continue
                if sig == base_sig:
                    skipped.append({"label": c["label"], "why": "no visible change"})
                    continue
                if sig in seen_sigs:
                    skipped.append({"label": c["label"],
                                    "why": "same view as '%s'" % seen_sigs[sig]})
                    continue
                seen_sigs[sig] = c["label"]
                action = ({"click": c["selector"]} if c["selector"]
                          else {"role": c["role"], "name": c["label"]})
                states.append({
                    "screen": screen, "name": slug(c["label"]),
                    "label": c["label"], "role": c["role"],
                    "actions": [action, {"wait": args.settle}],
                })
                print("  + %-34s -> new view" % c["label"][:34])
        browser.close()

    out = {"screen": screen, "viewport": viewport,
           "candidates": candidates, "states": states, "skipped": skipped}
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print("\n%d distinct states, %d candidates skipped" % (len(states), len(skipped)))
    print("states: %s" % args.out)
    if not args.probe:
        print("run again with --probe to find which ones actually change the view")
    return 0


if __name__ == "__main__":
    sys.exit(main())
