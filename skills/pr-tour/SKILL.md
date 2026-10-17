---
name: pr-tour
description: Guided tour of a GitHub PR or GitLab MR for a human reviewer, cutting the diff into changestacks (one concern each) in reading order, each with risk, a diagram or pseudocode, links into the diff, and its open review threads. Use when the user wants to review a PR/MR themselves, asks to walk through, tour, or group a PR's changes, or runs /pr-tour. Args: <n|url|base..head> [--post].
---

The reader is a human about to review. Give them a **tour**: the diff cut into **changestacks**, one concern each, in the order a reviewer should read them, each shown as a picture of what it does with the open review threads sitting next to the code they are about. They comment in GitHub/GitLab through the links; the tour only decides what to look at, in what order, and what it means.

`tour.py` sits next to this file. Run it as `python3 <this skill's dir>/tour.py`.

## 1. Fetch

- `base..head`: range mode, no platform. `BASE=$(git merge-base <base> <head>)`, `HEAD_SHA=$(git rev-parse <head>)`, no URL, skip step 4.
- URL containing `/-/merge_requests/`, or origin not on `github.com` and `glab api projects/:id/merge_requests/<n>` succeeds: GitLab.
- Otherwise: GitHub.

| | GitHub | GitLab |
|---|---|---|
| Metadata | `gh pr view <n> --json title,body,url,baseRefName,headRefOid` | `glab api projects/:id/merge_requests/<n>`: `title`, `description`, `web_url`, `target_branch`, `sha`, `diff_refs.base_sha` |
| Refs | `git fetch origin <baseRefName> pull/<n>/head` | `git fetch origin <target_branch> merge-requests/<n>/head` |
| `BASE` | `git merge-base origin/<baseRefName> <headRefOid>` | `diff_refs.base_sha` |

Done when you hold `BASE`, `HEAD_SHA`, the URL, and the description (the **intent**).

## 2. Read

`tour.py hunks $BASE $HEAD_SHA` lists every hunk as `H<n>  <path>  <span>  <context>`. Read `git diff $BASE $HEAD_SHA` alongside it, file by file for a large diff, and open surrounding code with `git show $HEAD_SHA:<path>` when a hunk's purpose is unclear from the diff.

Done when you can say, for every hunk, which concern it serves.

## 3. Stack

Write `changestacks.json` in a `mktemp -d` dir:

```json
{"changestacks": [
  {"title": "Scroll sync between panes", "risk": "high",
   "why": "One sentence: what the reviewer should check here.",
   "visual": ["```mermaid", "sequenceDiagram", "  Left->>Hook: scroll", "  Hook->>Right: mirror offset", "```"],
   "hunks": ["H3", "H4", "src/diff/useSyncedScroll.ts"]}
]}
```

- One changestack per **concern**: a reason the code changed, named by behaviour ("Retry on token expiry"), not by file or layer.
- Tests go in the changestack of the code they test, so behaviour and its proof are read together.
- Order is reading order: the change the intent describes first, then what it forces elsewhere, then **mechanical** work (renames, formatting, lockfiles, generated files) last in one `low` changestack.
- `risk`: `high` touches behaviour, data, security, or a contract others call; `low` is mechanical; `medium` is the rest.
- `why` names what to verify, from what you read in step 2 ("both panes must stop listening on unmount"), not a summary of the diff.
- `hunks`: a path takes every hunk of that file; use it when a whole file serves one concern.
- A one-concern PR gets one changestack.

### Visual

Every changestack except the mechanical one gets a `visual`: the smallest view that shows what it does, one fenced block as an array of lines. Pick by what changed:

| Changed | View |
|---|---|
| logic, an algorithm, state handling | pseudocode (`text`), or a `diff` of the pseudocode when the old shape exists |
| who calls what at runtime | call tree (`text`), or a `diff` of the call tree |
| components talking, data flow, ordering | `mermaid` (`sequenceDiagram`, `flowchart`) |
| UI structure | component tree with the state and module boundaries that matter |
| file responsibilities, a broad refactor | shallow file tree with one `# role` comment per entry |

Keep only the calls, files, states, and boundaries the reviewer needs for this changestack's `why`. Use real names from the code, and draw what the code does, not what the PR description says it does.

## 4. Threads

`tour.py threads <url> > $T/threads.json`. Unresolved threads get attached to the changestack whose hunk is nearest their line. Bot authors are tagged `(bot)`.

## 5. Render

`tour.py render $BASE $HEAD_SHA $T/changestacks.json --threads $T/threads.json --url <url>` (range mode: drop `--threads` and `--url`).

It exits 1 listing every hunk that is unstacked, in two changestacks, or unknown, and every visual with an unclosed fence. Fix `changestacks.json` by moving each hunk to the concern it serves, and re-run.

Done when it exits 0.

## 6. Present

Print a title line (`# Tour of <title>`), then the render output verbatim. Close with one line naming where to start: the first `high` changestack, or the one with the most open human threads if that differs.

With `--post`, write that same tour to `$T/tour.md` and run `tour.py post <url> $T/tour.md`. It edits the tour comment from an earlier run, so the PR/MR carries one current tour, and prints the comment's URL. Range mode has nowhere to post: say so and print only.
