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

CHROME_REGIONS = r"""
() => {
  // Containers that exist to drive the prototype. Their geometry is returned so
  // the build step can exclude the region from the imported screen frame.
  const PROTO_ID = /proto|demo|mock(up)?|switcher|screen-?(nav|select)|view-?(nav|select|switch)|state-?(nav|select)|storybook|preview-?(nav|bar)|flow-?(nav|select)/i;
  const out = [];
  document.querySelectorAll('body *').forEach((el) => {
    const idc = (el.id || '') + ' ' +
      (typeof el.className === 'string' ? el.className : '') + ' ' +
      (el.getAttribute('data-testid') || '');
    if (!PROTO_ID.test(idc)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 12) return;
    // Skip if an ancestor already matched, so only the outermost region is kept.
    let p = el.parentElement, nested = false;
    while (p && !nested) {
      const pid = (p.id || '') + ' ' +
        (typeof p.className === 'string' ? p.className : '');
      if (PROTO_ID.test(pid)) nested = true;
      p = p.parentElement;
    }
    if (nested) return;
    out.push({
      id: el.id || null,
      cls: (typeof el.className === 'string' ? el.className : '').slice(0, 80),
      x: Math.round(r.x), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
      text: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60),
    });
  });
  return out;
}
"""

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
    // Prototype scaffolding: controls the author added to navigate the mock,
    // not part of the product UI. Detected from the element's own identity and
    // from any ancestor that declares itself a prototype/demo container.
    const PROTO_ID = /proto|demo|mock(up)?|switcher|screen-?(nav|select)|view-?(nav|select|switch)|state-?(nav|select)|storybook|preview-?(nav|bar)|flow-?(nav|select)/i;
    const PROTO_LABEL = /^(view|screen|state|step|variant|flow|page|frame)\s*[-#]?\s*\d+$/i;
    const PROTO_WORDS = /\b(prototype|demo|mockup|next screen|previous screen|prev screen|reset demo|switch view|toggle view|view switcher|screen selector)\b/i;
    let proto = false, protoWhy = null;
    if (PROTO_LABEL.test(label)) { proto = true; protoWhy = 'label looks like a view index'; }
    if (PROTO_WORDS.test(label)) { proto = true; protoWhy = 'label names the prototype itself'; }
    let a = el, hops2 = 0;
    while (!proto && a && hops2 < 6) {
      const idc = ((a.id || '') + ' ' + (typeof a.className === 'string' ? a.className : '') + ' ' +
                   (a.getAttribute && (a.getAttribute('data-testid') || '')));
      if (PROTO_ID.test(idc)) { proto = true; protoWhy = 'inside a prototype/demo container'; }
      a = a.parentElement; hops2++;
    }
    out.push({
      label, role, tag: el.tagName.toLowerCase(), selector: sel,
      ariaExpanded: el.getAttribute('aria-expanded'),
      ariaSelected: el.getAttribute('aria-selected'),
      dataState: el.getAttribute('data-state'),
      x: Math.round(r.x), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
      prototypeChrome: proto, prototypeWhy: protoWhy,
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
    ap.add_argument("--depth", type=int, default=1,
                    help="probe depth. 1 = top level only. 2 = also probe INSIDE each "
                         "discovered state, which is the only way nested flows (a modal's "
                         "own view pickers, toggles and tabs) are found. Use 2 whenever "
                         "any state is a modal, drawer or overlay.")
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
        chrome_regions = page.evaluate(CHROME_REGIONS)
        base_sig = hashlib.md5(page.evaluate(SIGNATURE).encode()).hexdigest()
        print("%d interactive elements found" % len(candidates))

        states, skipped = [], []
        seen_sigs = {base_sig: "default"}

        def apply(actions):
            """Replay a state's actions on a freshly loaded page."""
            for a in actions:
                if "role" in a and "name" in a:
                    page.get_by_role(a["role"], name=a["name"], exact=True) \
                        .first.click(timeout=3000)
                elif a.get("click"):
                    page.click(a["click"], timeout=3000)
                elif "wait" in a:
                    page.wait_for_timeout(int(a["wait"]))
            page.wait_for_timeout(args.settle)

        if args.probe:
            probeable = [c for c in candidates if not SKIP.match(c["label"])]
            print("probing %d of them (cap %d)…" %
                  (min(len(probeable), args.max_probes), args.max_probes))
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
                    # Reached via prototype navigation: the resulting VIEW is a real
                    # screen, but the switcher chrome must not be drawn into it.
                    "via": "prototype-nav" if c.get("prototypeChrome") else "product-ui",
                    "actions": [action, {"wait": args.settle}],
                })
                print("  + %-34s -> new view" % c["label"][:34])
        # --- depth 2+: probe INSIDE each discovered state ----------------------
        # A modal's own view pickers, toggles and tabs only exist once the modal
        # is open. Single-level probing cannot see them, which silently drops
        # whole branches of the flow.
        if args.probe and args.depth > 1:
            for parent in list(states):
                if parent.get("depth", 1) >= args.depth:
                    continue
                try:
                    load()
                    apply(parent["actions"])
                    parent_sig = hashlib.md5(page.evaluate(SIGNATURE).encode()).hexdigest()
                    inner = page.evaluate(ENUMERATE)
                except Exception as e:
                    skipped.append({"label": parent["name"],
                                    "why": "could not re-enter: " + str(e)[:80]})
                    continue
                outer = set(c["label"] for c in candidates)
                fresh = [c for c in inner
                         if c["label"] not in outer and not SKIP.match(c["label"])]
                if fresh:
                    print("  inside '%s': %d nested control(s)" % (parent["name"], len(fresh)))
                for c in fresh[:args.max_probes]:
                    action = ({"click": c["selector"]} if c["selector"]
                              else {"role": c["role"], "name": c["label"]})
                    try:
                        load()
                        apply(parent["actions"])
                        if c["selector"]:
                            page.click(c["selector"], timeout=3000)
                        else:
                            page.get_by_role(c["role"], name=c["label"], exact=True) \
                                .first.click(timeout=3000)
                        page.wait_for_timeout(args.settle)
                        sig = hashlib.md5(page.evaluate(SIGNATURE).encode()).hexdigest()
                    except Exception as e:
                        skipped.append({"label": parent["name"] + " > " + c["label"],
                                        "why": str(e).split("\n")[0][:100]})
                        continue
                    if sig == parent_sig or sig in seen_sigs:
                        skipped.append({"label": parent["name"] + " > " + c["label"],
                                        "why": "no new view"})
                        continue
                    seen_sigs[sig] = parent["name"] + " > " + c["label"]
                    states.append({
                        "screen": screen,
                        "name": slug(parent["name"] + "-" + c["label"]),
                        "label": c["label"], "role": c["role"],
                        "parent": parent["name"], "depth": 2,
                        "via": "prototype-nav" if c.get("prototypeChrome") else "product-ui",
                        "actions": parent["actions"] + [action, {"wait": args.settle}],
                    })
                    print("    + %-38s -> nested view" % c["label"][:38])

        browser.close()

    proto_states = [s for s in states if s.get("via") == "prototype-nav"]
    out = {"screen": screen, "viewport": viewport,
           "candidates": candidates, "states": states, "skipped": skipped,
           "prototype_chrome_regions": chrome_regions,
           "prototype_nav_states": len(proto_states),
           "note": ("Regions in prototype_chrome_regions are authoring scaffolding, "
                    "not product UI. Exclude them from every imported screen frame. "
                    "States with via=prototype-nav are still real screens - only the "
                    "switcher chrome is excluded.")}
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print("\n%d distinct states, %d candidates skipped" % (len(states), len(skipped)))
    if chrome_regions:
        print("%d prototype chrome region(s) detected - EXCLUDE these from screens:"
              % len(chrome_regions))
        for r in chrome_regions[:6]:
            print("   %s  %dx%d at (%d,%d)  %s"
                  % (r["id"] or r["cls"][:24] or "?", r["w"], r["h"], r["x"], r["y"],
                     r["text"][:32]))
    if proto_states:
        print("%d state(s) reached via prototype navigation (kept as screens)"
              % len(proto_states))
    print("states: %s" % args.out)
    if not args.probe:
        print("run again with --probe to find which ones actually change the view")
    return 0


if __name__ == "__main__":
    sys.exit(main())
