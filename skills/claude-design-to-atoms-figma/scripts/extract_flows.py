#!/usr/bin/env python3
"""Derive the screen graph (screens, states, transitions) from the design source.

Usage:
  extract_flows.py RUNDIR --out flows.json [--markdown FLOWS.md]

Heuristics only. Always review the output against the markup — dynamic
navigation (computed hrefs, event delegation) will not be caught.
"""
import argparse
import json
import os
import re
import sys

STRIP_TAGS = re.compile(r"<[^>]+>")


def text_of(s):
    return re.sub(r"\s+", " ", STRIP_TAGS.sub("", s)).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def find_states(html):
    """Client-side views: data attributes, class toggles, state enums, route tables."""
    states = []

    def add(name, kind, trigger=None, evidence=None):
        if not name:
            return
        states.append({"name": name, "kind": kind, "trigger": trigger,
                       "evidence": evidence})

    for m in re.finditer(r'data-(?:screen|view|page|step)=["\']([^"\']+)["\']', html):
        add(m.group(1), "screen", None, "data-attr")
    for m in re.finditer(r'id=["\']([a-zA-Z0-9_-]*(?:modal|dialog|drawer|sheet|popup|overlay)[a-zA-Z0-9_-]*)["\']',
                         html, re.I):
        add(m.group(1), "modal", None, "id")
    # Bare generic class names carry no screen identity — an id or a compound
    # class ("delete-modal") does. Skip the bare ones to keep the graph readable.
    GENERIC = {"modal", "dialog", "drawer", "toast", "skeleton", "overlay", "popup"}
    for m in re.finditer(r'class=["\']([^"\']*\b(?:modal|dialog|drawer|toast|empty-state|error-state|skeleton)\b[^"\']*)["\']',
                         html, re.I):
        cls = [c for c in m.group(1).split()
               if re.search(r"modal|dialog|drawer|toast|empty-state|error-state|skeleton", c, re.I)
               and c.lower() not in GENERIC]
        for c in cls:
            kind = "modal"
            if re.search(r"toast", c, re.I):
                kind = "state"
            elif re.search(r"empty", c, re.I):
                kind = "empty"
            elif re.search(r"error", c, re.I):
                kind = "error"
            elif re.search(r"skeleton", c, re.I):
                kind = "state"
            add(c, kind, None, "class")
    # React-ish string state enums: setView('billing') / useState('overview')
    for m in re.finditer(r"set(?:View|Screen|Page|Step|Tab|Route)\s*\(\s*['\"]([^'\"]+)['\"]", html):
        add(m.group(1), "screen", "state setter", "setState")
    for m in re.finditer(r"useState\(\s*['\"]([a-zA-Z0-9 _-]{2,40})['\"]\s*\)", html):
        add(m.group(1), "screen", "initial state", "useState")
    # Route tables
    for m in re.finditer(r'path\s*:\s*["\']([^"\']+)["\']', html):
        add(m.group(1), "screen", None, "route-table")
    for m in re.finditer(r'<Route[^>]+path=["\']([^"\']+)["\']', html):
        add(m.group(1), "screen", None, "react-router")
    for m in re.finditer(r"location\.hash\s*===?\s*['\"]#?([^'\"]+)['\"]", html):
        add(m.group(1), "screen", "hash change", "hash-router")
    # Dedupe, keep first evidence
    seen, out = set(), []
    for s in states:
        k = (slug(s["name"]), s["kind"])
        if k in seen or not slug(s["name"]):
            continue
        seen.add(k)
        out.append(s)
    return out


def find_triggers(html):
    """Buttons/links and what they appear to open."""
    trig = []
    for m in re.finditer(r"<(a|button)\b([^>]*)>(.*?)</\1>", html, re.S | re.I):
        attrs, inner = m.group(2), m.group(3)
        label = text_of(inner)[:60]
        href = re.search(r'href=["\']([^"\']+)["\']', attrs)
        onclick = re.search(r'onclick=["\']([^"\']+)["\']', attrs)
        target = re.search(r'data-(?:target|screen|view|modal|opens)=["\']([^"\']+)["\']', attrs)
        dest = None
        if href and not href.group(1).startswith(("http", "mailto:", "tel:", "#")):
            dest = href.group(1)
        elif href and href.group(1).startswith("#") and len(href.group(1)) > 1:
            dest = href.group(1)[1:]
        elif target:
            dest = target.group(1)
        elif onclick:
            call = re.search(r"['\"]([a-zA-Z0-9 _/-]{2,40})['\"]", onclick.group(1))
            if call:
                dest = call.group(1)
        if label or dest:
            trig.append({"label": label, "to": dest, "element": m.group(1).lower()})
    return trig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown")
    args = ap.parse_args()

    inv_path = os.path.join(args.run, "inventory.json")
    if not os.path.exists(inv_path):
        print("no inventory.json — run ingest_design.py first", file=sys.stderr)
        return 1
    inv = json.load(open(inv_path))
    src_dir = inv["src_dir"]

    nodes, edges = [], []
    by_file = {}

    for s in inv["screens"]:
        html = read(os.path.join(src_dir, s["file"]))
        name = s.get("title") or s.get("h1") or os.path.splitext(os.path.basename(s["file"]))[0]
        nid = slug(name) or slug(s["file"])
        by_file[s["file"]] = nid
        nodes.append({"id": nid, "title": name, "kind": "screen",
                      "source": s["file"], "is_entry": s["file"] == inv.get("entry_point")})
        for st in find_states(html):
            sid = "%s__%s" % (nid, slug(st["name"]))
            nodes.append({"id": sid, "title": st["name"], "kind": st["kind"],
                          "source": s["file"], "parent": nid,
                          "evidence": st["evidence"], "is_entry": False})
            edges.append({"from": nid, "to": sid, "trigger": st["trigger"] or st["evidence"],
                          "confidence": "heuristic"})
        for t in find_triggers(html):
            if not t["to"]:
                continue
            edges.append({"from": nid, "to_raw": t["to"], "trigger": t["label"] or t["element"],
                          "confidence": "heuristic"})

    ids = set(n["id"] for n in nodes)
    resolved, unresolved = [], []
    for e in edges:
        if "to" in e:
            resolved.append(e)
            continue
        raw = e.pop("to_raw")
        cand = by_file.get(raw) or by_file.get(raw.lstrip("./"))
        if not cand:
            base = slug(os.path.splitext(os.path.basename(raw))[0])
            cand = base if base in ids else None
            if not cand:
                for n in nodes:
                    if n["id"].endswith("__%s" % slug(raw)):
                        cand = n["id"]
                        break
        if cand:
            e["to"] = cand
            resolved.append(e)
        else:
            e["to"] = None
            e["raw"] = raw
            unresolved.append(e)

    # dedupe edges
    seen, uniq = set(), []
    for e in resolved:
        k = (e["from"], e["to"], e.get("trigger"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)

    for n in nodes:
        n["to"] = sorted(set(e["to"] for e in uniq if e["from"] == n["id"] and e["to"]))
        n["from"] = sorted(set(e["from"] for e in uniq if e["to"] == n["id"]))

    # Flow order: entry first, then BFS, then anything orphaned.
    entry = next((n["id"] for n in nodes if n.get("is_entry")), nodes[0]["id"] if nodes else None)
    order, queue, seen_o = [], [entry] if entry else [], set()
    node_by_id = dict((n["id"], n) for n in nodes)
    while queue:
        cur = queue.pop(0)
        if cur in seen_o or cur not in node_by_id:
            continue
        seen_o.add(cur)
        order.append(cur)
        queue.extend(node_by_id[cur]["to"])
    for n in nodes:
        if n["id"] not in seen_o:
            order.append(n["id"])

    flows = {"entry": entry, "order": order, "nodes": nodes, "edges": uniq,
             "unresolved_edges": unresolved,
             "counts": {"nodes": len(nodes), "edges": len(uniq),
                        "unresolved": len(unresolved)}}
    with open(args.out, "w") as fh:
        json.dump(flows, fh, indent=2)

    if args.markdown:
        lines = ["# Flows", "", "Entry: **%s**" % entry, "",
                 "%d nodes, %d edges, %d unresolved links." % (
                     len(nodes), len(uniq), len(unresolved)), "",
                 "## Build order", ""]
        for i, nid in enumerate(order, 1):
            n = node_by_id.get(nid, {})
            lines.append("%d. `%s` — %s (%s)" % (i, nid, n.get("title", "?"), n.get("kind", "?")))
        lines += ["", "## Transitions", "",
                  "| From | Trigger | To |", "|---|---|---|"]
        for e in uniq:
            lines.append("| %s | %s | %s |" % (e["from"], e.get("trigger") or "", e["to"]))
        if unresolved:
            lines += ["", "## Unresolved links (resolve these by reading the markup)", "",
                      "| From | Trigger | Raw target |", "|---|---|---|"]
            for e in unresolved:
                lines.append("| %s | %s | `%s` |" % (e["from"], e.get("trigger") or "", e["raw"]))
        lines += ["", "> Heuristic output. Verify against the source before building — "
                  "dynamic navigation is not detected.", ""]
        with open(args.markdown, "w") as fh:
            fh.write("\n".join(lines))

    print("%d nodes, %d edges, %d unresolved" % (len(nodes), len(uniq), len(unresolved)))
    print("order: %s" % " -> ".join(order[:8]) + (" ..." if len(order) > 8 else ""))
    print("flows: %s%s" % (args.out, "  %s" % args.markdown if args.markdown else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
