#!/usr/bin/env python3
"""Unpack a Claude design deliverable and inventory its screens.

Usage:
  ingest_design.py <source.zip|folder|file.html> --out RUNDIR
"""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile

SKIP_DIRS = {"node_modules", ".git", "__MACOSX", "dist-cache", ".next", ".vercel"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico"}


def unpack(source, run):
    src_dir = os.path.join(run, "src")
    if os.path.isdir(source):
        if os.path.abspath(source) != os.path.abspath(src_dir):
            if os.path.exists(src_dir):
                shutil.rmtree(src_dir)
            shutil.copytree(source, src_dir,
                            ignore=shutil.ignore_patterns(*SKIP_DIRS))
        return src_dir, "folder"
    os.makedirs(src_dir, exist_ok=True)
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            for m in z.namelist():
                # Refuse absolute paths and traversal before writing anything.
                if m.startswith("/") or ".." in m.split("/"):
                    print("skipping unsafe zip entry: %s" % m, file=sys.stderr)
                    continue
                if any(p in SKIP_DIRS for p in m.split("/")):
                    continue
                z.extract(m, src_dir)
        # A zip with a single top-level folder: flatten one level.
        entries = [e for e in os.listdir(src_dir) if not e.startswith(".")]
        if len(entries) == 1 and os.path.isdir(os.path.join(src_dir, entries[0])):
            inner = os.path.join(src_dir, entries[0])
            for e in os.listdir(inner):
                shutil.move(os.path.join(inner, e), os.path.join(src_dir, e))
            os.rmdir(inner)
        return src_dir, "zip"
    shutil.copy2(source, os.path.join(src_dir, os.path.basename(source)))
    return src_dir, "file"


def walk(src_dir):
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            yield os.path.join(root, f)


def detect_framework(html, path_list):
    marks = []
    if re.search(r"cdn\.tailwindcss\.com|tailwindcss@", html):
        marks.append("tailwind-cdn")
    if re.search(r'rel=["\']stylesheet["\'][^>]*tailwind', html, re.I):
        marks.append("tailwind-build")
    if re.search(r"unpkg\.com/@babel|babel\.min\.js", html):
        marks.append("react-in-page-babel")
    if re.search(r"react(-dom)?(\.production|\.development)?\.min\.js|esm\.sh/react", html):
        marks.append("react")
    if re.search(r'type=["\']module["\'][^>]*src=["\'][^"\']*assets/', html):
        marks.append("vite-build")
    if any(p.endswith("package.json") for p in path_list):
        marks.append("has-package-json")
    if not marks:
        marks.append("plain-html")
    return marks


def spa_signals(html):
    sig = []
    pats = [
        (r"\bwindow\.location\.hash\b|addEventListener\(\s*['\"]hashchange", "hash-router"),
        (r"\bhistory\.pushState\b", "history-router"),
        (r"createBrowserRouter|<Routes>|<Route\b|useNavigate", "react-router"),
        (r"data-screen=|data-view=|data-page=", "data-attr-views"),
        (r"\.(screen|view|page)\.active|classList\.(add|toggle)\(\s*['\"]active", "class-toggle-views"),
        (r"set(View|Screen|Page|Step|Tab)\s*\(", "state-setter-views"),
        (r"useState\(\s*['\"][a-z-]+['\"]\s*\)", "string-state-enum"),
    ]
    for pat, name in pats:
        if re.search(pat, html):
            sig.append(name)
    return sig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", required=True, help="run directory")
    args = ap.parse_args()

    run = os.path.abspath(args.out)
    os.makedirs(run, exist_ok=True)
    src_dir, kind = unpack(os.path.abspath(args.source), run)

    all_files = list(walk(src_dir))
    rel = lambda p: os.path.relpath(p, src_dir)
    rel_all = [rel(p) for p in all_files]

    html_files, css_files, js_files, images, others = [], [], [], [], []
    for p in all_files:
        ext = os.path.splitext(p)[1].lower()
        if ext in (".html", ".htm"):
            html_files.append(p)
        elif ext == ".css":
            css_files.append(p)
        elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
            js_files.append(p)
        elif ext in IMG_EXT:
            images.append(p)
        else:
            others.append(p)

    screens = []
    for p in sorted(html_files):
        try:
            html = open(p, encoding="utf-8", errors="replace").read()
        except OSError as e:
            print("cannot read %s: %s" % (p, e), file=sys.stderr)
            continue
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()
        links = sorted(set(
            m.group(1) for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not m.group(1).startswith(("http://", "https://", "mailto:", "tel:"))
        ))
        screens.append({
            "file": rel(p),
            "title": strip(title.group(1)) if title else None,
            "h1": strip(h1.group(1)) if h1 else None,
            "bytes": os.path.getsize(p),
            "inline_style_blocks": len(re.findall(r"<style", html, re.I)),
            "linked_stylesheets": re.findall(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\']', html, re.I),
            "inline_script_blocks": len(re.findall(r"<script(?![^>]*\bsrc=)", html, re.I)),
            "data_uri_images": len(re.findall(r'src=["\']data:image/', html, re.I)),
            "remote_images": sorted(set(re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', html, re.I)))[:50],
            "internal_links": links,
            "framework": detect_framework(html, rel_all),
            "spa_signals": spa_signals(html),
        })

    entry = None
    for cand in ("index.html", "home.html", "main.html", "app.html"):
        for s in screens:
            if os.path.basename(s["file"]).lower() == cand:
                entry = s["file"]
                break
        if entry:
            break
    if not entry and screens:
        entry = max(screens, key=lambda s: s["bytes"])["file"]

    inv = {
        "source": os.path.abspath(args.source),
        "source_kind": kind,
        "src_dir": src_dir,
        "entry_point": entry,
        "multi_file": len(screens) > 1,
        "likely_spa": bool(screens and screens[0]["spa_signals"]) and len(screens) == 1,
        "counts": {
            "html": len(html_files), "css": len(css_files), "js": len(js_files),
            "images": len(images), "other": len(others),
        },
        "screens": screens,
        "css_files": [rel(p) for p in sorted(css_files)],
        "js_files": [rel(p) for p in sorted(js_files)],
        "images": [rel(p) for p in sorted(images)],
    }
    out = os.path.join(run, "inventory.json")
    with open(out, "w") as fh:
        json.dump(inv, fh, indent=2)

    print("unpacked %s (%s) -> %s" % (args.source, kind, src_dir))
    print("%d html, %d css, %d js, %d images" % (
        len(html_files), len(css_files), len(js_files), len(images)))
    print("entry point: %s" % entry)
    if inv["likely_spa"]:
        print("single-page app: views are switched client-side (%s)"
              % ", ".join(screens[0]["spa_signals"]))
    print("inventory: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
