# Flow extraction

`extract_flows.py` is a heuristic pass over the markup. It finds the patterns below; anything computed at runtime it will miss, which is why Phase 5 requires you to read the source and correct `flows.json` before building.

## Patterns and what each means

| Source pattern | Flow meaning |
|---|---|
| `<a href="settings.html">` across multiple HTML files | screen → screen edge, trigger = link label |
| `<a href="#billing">` with a hash router | screen → view edge |
| `data-screen` / `data-view` / `data-page` attributes | each value is a screen in one file |
| `.screen.active` / `classList.toggle('active')` | view switching; the initially-active one is the entry |
| `setView('x')`, `setStep(2)`, `setTab('y')` | state-driven views; the `useState` initial value is the entry |
| `useState('overview')` with string enums | the enum values are the screen list |
| `createBrowserRouter` / `<Route path>` / `path:` tables | authoritative screen list — prefer this over class heuristics |
| ids/classes containing `modal`, `dialog`, `drawer`, `sheet`, `popup` | a state hanging off its parent screen, not a top-level screen |
| `toast`, `skeleton`, `empty-state`, `error-state` | a state variant worth its own frame if it is visually distinct |
| `<form>` with a submit handler that switches view | screen → screen edge, trigger = the submit button label |

## What to do after running it

1. **Check the entry point.** The script guesses `index.html` or the largest file. If the design's real start is a login or empty state, fix `entry`.
2. **Collapse duplicates.** A nav rendered on every page produces the same edges N times; they are deduped by (from, to, trigger) but the same destination reached from a nav and a CTA are two legitimate edges — keep both only if the user cares about the distinction. Usually keep one and note the other triggers.
3. **Resolve `unresolved_edges`.** Every row there is a link whose destination could not be matched to a node. Read the handler and either point it at a node or drop it (external links, `#`, `javascript:void(0)`).
4. **Decide which states get frames.** Rule of thumb: a state gets its own frame if a stakeholder would review it — empty, error, loading, success, each modal, each destructive confirm. Hover/focus micro-states do not.
5. **Set the order.** The generated BFS order is a starting point. Reorder into the narrative the user will present: happy path left to right, alternates and errors on the row below their parent.

## Multi-viewport designs

If the design is responsive and the user wants mobile too, capture a second viewport (`--viewport 390x844`) and treat each breakpoint as a **parallel row** of the same flow, named `<NN> <Screen> · Mobile`. Do not interleave breakpoints in one row — it makes the flow unreadable.

## Nested states: probe more than one level

The most damaging discovery failure is **silent**: probing only the top level finds a modal, but never the view pickers, mode toggles and tabs that exist *inside* it. Whole branches of the flow go missing and nothing reports an error.

```bash
python3 "$SKILL"/scripts/discover_states.py "$RUN" --out "$RUN/states.json" \
  --probe --depth 2 --max-probes 22
```

At `--depth 2` the script re-enters each discovered state (replaying its action list on a fresh page), enumerates the controls that were not present at the top level, and probes those too. Nested states carry `parent` and `depth: 2`, and their `actions` array is the full path from the entry point.

**Default to `--depth 2` whenever any state is a modal, drawer or overlay.** A compare dialog with its own "view" selector and a screens/details toggle produces three distinct screens, only one of which depth-1 discovery can see.

Reconcile before you declare the import complete: list the discovered states, list the frames you built, and diff them. A state that exists in the capture but has no frame is a missing screen, not an acceptable omission.
