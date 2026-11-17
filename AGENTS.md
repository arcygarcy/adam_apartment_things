# Agent Guidelines (`AGENTS.md`)

All architectural decisions, hardware constraints, and behavioral rules for this repository are documented in **[`DECISIONS.md`](./DECISIONS.md)**.

## Instructions for AI Agents
1. **Check `DECISIONS.md` before making changes:**
   - Start by reading the **Table of Contents** at the top of [`DECISIONS.md`](./DECISIONS.md) (`lines 1–25`) to identify which sections apply to your current task, then read the relevant section(s).
2. **Keep `DECISIONS.md` up to date:**
   - **Append by default:** When a new feature, fix, or architectural decision is made, append a new detailed section at the bottom of [`DECISIONS.md`](./DECISIONS.md) and add an entry to its **Table of Contents** at the top.
   - **Overwrite when superseded:** If a new decision changes or replaces an existing behavior documented in [`DECISIONS.md`](./DECISIONS.md), **overwrite/update the existing section and its Table of Contents entry** rather than leaving conflicting historical entries.
3. **Keep `AGENTS.md` lightweight:**
   - Because `AGENTS.md` is automatically loaded into the agent's context on every turn, keep detailed decision logs inside [`DECISIONS.md`](./DECISIONS.md) rather than in this file.
