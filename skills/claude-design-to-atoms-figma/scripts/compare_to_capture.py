#!/usr/bin/env python3
"""Text-parity check: is a built Figma screen actually complete?

The most damaging build failure is not a wrong colour, it is a screen that is
*underbuilt* - a placeholder where the source has a whole rebuilt region. That
is invisible to a style audit and easy to miss by eye, but it is trivially
measurable: every visible string in the captured state should appear in the
built frame.

Usage:
  1. Dump the built frames' text with a use_figma read, saved as:
       {"<frame name>": ["string", ...], ...}
  2. compare_to_capture.py RUNDIR --built built-text.json \
         --map "13 Compare step — screens only=compare-runs" [--map ...] \
         [--capture capture2] [--threshold 0.8]

Exits non-zero when any mapped screen falls below the threshold.
"""
import argparse
import json
import os
import re
import sys


def norm(s):
    s = (s or "").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def capture_texts(run, capture, state):
    p = os.path.join(run, capture, state + ".computed.json")
    if not os.path.exists(p):
        return None
    data = json.load(open(p))
    out = []
    for e in data.get("elements", []):
        t = norm(e.get("text"))
        if t and len(t) > 1:
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--built", required=True, help="JSON: {frame name: [text, ...]}")
    ap.add_argument("--map", action="append", default=[],
                    help="'<frame name>=<capture state>' (repeatable)")
    ap.add_argument("--capture", default="capture")
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    built = json.load(open(args.built))
    pairs = []
    for m in args.map:
        if "=" not in m:
            print("bad --map (need frame=state): %s" % m, file=sys.stderr)
            return 2
        frame, state = m.split("=", 1)
        pairs.append((frame.strip(), state.strip()))

    failed = 0
    print("%-44s %7s %7s  %s" % ("screen", "source", "built", "coverage"))
    print("-" * 78)
    for frame, state in pairs:
        src = capture_texts(args.run, args.capture, state)
        if src is None:
            print("%-44s   capture '%s' not found" % (frame[:44], state))
            failed += 1
            continue
        have = set(norm(t) for t in built.get(frame, []))
        # A source string counts as present if it appears in any built string
        # (a label may be merged into a longer run in Figma).
        joined = " || ".join(have)
        found = [t for t in set(src) if t in have or t in joined]
        missing = [t for t in set(src) if t not in have and t not in joined]
        uniq = len(set(src))
        cov = len(found) / uniq if uniq else 1.0
        flag = "OK " if cov >= args.threshold else "UNDERBUILT"
        print("%-44s %7d %7d  %5.1f%%  %s" % (frame[:44], uniq, len(have), cov * 100, flag))
        if cov < args.threshold:
            failed += 1
            for t in sorted(missing)[:args.show]:
                print("        missing: %s" % t[:66])
            if len(missing) > args.show:
                print("        ... and %d more" % (len(missing) - args.show))
    print()
    if failed:
        print("%d screen(s) below %.0f%% text parity - rebuild them before shipping"
              % (failed, args.threshold * 100))
        return 1
    print("all screens meet the text-parity threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
