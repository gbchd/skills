---
name: explain
description: Explain one slice of the codebase before you change it, grounded in the code as it is today.
disable-model-invocation: true
argument-hint: "Which part of the code do you want explained?"
---

The user wants to understand one **slice** of this codebase, usually because they are about to change it. The explainer stands in for what they would have learned reading teammates' diffs in review. Explain the slice, not the codebase, and size the explainer to the slice: a small slice gets a short one.

## Steps

1. **Pin the slice.** Restate the request as one flow or module with a clear boundary (e.g. "how managed settings are loaded, from startup to first read"). If it could mean two different slices, ask which.
2. **Trace it in the code.** Find the entry points and follow the real call path end to end, reading every file on it. Done when every claim you will make points at a `file:line` you have read.
3. **Check recent history.** Run `git log -n 10 --format='%h %an %ar %s' -- <core files>`: what changed lately, and who works on it. Skip outside a git repo.
4. **Write the explainer** in the terminal, filling each section only from what you read and dropping any section with nothing real to say:
   - **Summary**: one paragraph on what the slice does and why it exists.
   - **Path**: numbered steps from entry point to outcome, each with `file:line`.
   - **State**: the key data structures and where state lives.
   - **Gotchas**: invariants, edge cases, and hidden coupling that bite whoever changes this code.
   - **Recent changes**: the notable commits from step 3.
   - **Start here**: the file and function to open first for the change they have in mind.
5. **Offer the visual.** When the path has enough moving parts that a diagram teaches better than prose, offer an artifact that visualizes it; build it if the user asks, or if they asked for one up front.
