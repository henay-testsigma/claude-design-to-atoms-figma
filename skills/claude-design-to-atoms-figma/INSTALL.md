# Install — claude-design-to-atoms-figma

Ports a Claude-generated design (zip / folder / .html / artifact URL) into Figma as screens and flows, remapping every color, type, radius and shadow value onto the Atoms design system instead of raw hex values.

## Install (user-level — available in every project)

```bash
mkdir -p ~/.claude/skills
unzip claude-design-to-atoms-figma.zip -d ~/.claude/skills/
```

Restart Claude Code (or start a new session) and run `/claude-design-to-atoms-figma`. If it does not appear, check that `~/.claude/skills/claude-design-to-atoms-figma/SKILL.md` exists.

## Install (project-level — ships with a repo, shared via git)

```bash
mkdir -p .claude/skills
unzip claude-design-to-atoms-figma.zip -d .claude/skills/
git add .claude/skills/claude-design-to-atoms-figma && git commit -m "Add design-to-Figma skill"
```

Everyone who clones the repo gets it. Set `SKILL=./.claude/skills/claude-design-to-atoms-figma` when the skill asks for its own path.

## Requirements

| Requirement | Why | Check |
|---|---|---|
| Figma MCP connected | all Figma reads/writes | `/mcp` lists a `figma` server |
| Figma plugin skills (`figma-use`, `figma-generate-design`) | this skill delegates canvas writes to them | installed with the official Figma plugin |
| Python 3.8+ | the five analysis scripts | `python3 -V` |
| Playwright + Chromium | renders each screen to read *computed* styles | `pip3 install playwright && python3 -m playwright install chromium` |
| Atoms library published, and added to your target file | tokens import by key; unpublished keys fail | Figma → Assets panel shows Atoms |

Playwright is strongly recommended, not optional in practice: a Tailwind-CDN design has almost no color literals in its markup, so without the render there is very little to map.

## First run

1. Have your Claude design (zip/html) and the Figma file you want screens drawn into.
2. Run `/claude-design-to-atoms-figma`, give it both.
3. Review `MAPPING.md` when asked — that ledger is the contract for the whole import. Approving a wrong mapping early is cheap; finding it after 20 screens is not.

Tokens are read from the Atoms file (`GLwCKePaKJEIEWzPsUOp1d`) by default. The target file is never defaulted — the skill always asks.

## Notes for maintainers

- Scripts are pure-stdlib Python except `capture_screens.py` (Playwright). No install step.
- `scripts/*.js` are pasted as `use_figma` scripts; they use top-level `await` because `use_figma` wraps them in an async context. `node --check` will reject them — that is expected, not a bug.
- To point the skill at a different design system, change the default `fileKey` in SKILL.md Phase 3. Nothing else is Atoms-specific — no hexes are hardcoded anywhere; they are always read live from the file.
