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
