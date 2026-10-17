---
name: pr-review
description: Review a GitHub PR or GitLab MR with parallel bug finders, majority-vote verification, severity-tagged inline comments, and round limits that make review converge. Use when the user asks to review or re-review a PR/MR, passes a PR/MR number or URL, or runs /pr-review. Args: <n|url|base..head> [quick|standard|deep] [--local] [--json].
---

Priority, in order: catch real bugs, then cut review rounds. Every posted comment costs a round, because an agent author fixes whatever it is told. Post only findings a skeptical reader would confirm from the code alone.

## Arguments

- `<n>` or URL: the PR/MR. `base..head`: a commit range; implies `--local`, round 1.
- Depth: `quick` | `standard` | `deep`. Default: `depth:` in the root `REVIEW.md`, else `standard`.
- `--local`: print the report, post nothing.
- `--json`: print only the findings as a JSON array `[{"file","line","severity","class","claim"}]`, nothing else (used by `evals/run.sh`).

## 1. Platform and checkout

Platform:
- URL containing `/pull/` → GitHub; `/-/merge_requests/` → GitLab.
- Else origin host is `github.com` → GitHub; else `glab api projects/:id/merge_requests/<n>` succeeds → GitLab; else GitHub (Enterprise).

Fetch the PR/MR (see **Platform commands**), then check out head in a throwaway worktree so the user's tree stays untouched:

```bash
git fetch origin <target_branch> pull/<n>/head     # GitLab: merge-requests/<n>/head
WT=$(mktemp -d) && git worktree add --detach "$WT" <head_sha>
BASE=$(git merge-base origin/<target_branch> <head_sha>)   # range mode: git merge-base <base> <head>
```

All subagents work in `$WT`.

Done when you hold: head sha, `$BASE`, title + description (the **intent**), and the worktree.

## 2. Round state

Read earlier comments (range mode: skip) and collect pr-review markers:
- summary: `<!-- pr-review:summary round=<r> sha=<sha> -->`
- finding: `<!-- pr-review:finding file=<path> class=<slug> -->`

Round = highest earlier `r` + 1, or 1 when none.

- **Round ≥ 4**: review is not converging. Post one summary asking the author to step back and reconsider the approach, naming the bug classes that keep recurring. Remove the worktree and stop.
- **Round ≥ 3**: scope is `git diff <last sha>..<head_sha>` (fall back to full scope if `git cat-file -e <last sha>` fails after a force-push).
- Otherwise scope is `git diff $BASE...<head_sha>`.

Every earlier finding (file + class + claim) goes on the **posted list**.

## 3. Context bundle

- **Intent**: PR body / MR description, classified as bug fix, feature, refactor, or other.
- Root `CLAUDE.md`.
- `REVIEW.md` at the root and in every ancestor directory of a changed file; nearest wins on conflict. Extract: what failure looks like here, always-flag rules, skip paths, nit cap (default 3), depth.
- Remove from scope: skip paths, lockfiles, generated and vendored files.

Pass the bundle, the scope command, and `$WT` verbatim to every subagent.

## 4. Find

Spawn finders in parallel in one message, each in fresh context with the bundle and its angle.
- `quick`: 1 finder covering all angles. `standard`: angles 1–3. `deep`: angles 1–5.

Angles:
1. **Correctness**: logic, edge cases, error paths, concurrency, data loss, leaks.
2. **Blast radius**: grep every caller and importer of each changed symbol; contracts the change breaks.
3. **Intent**: the diff does what the intent claims. For a bug fix, the fix sits at the root cause and covers every caller, beyond the reported path.
4. **Conventions**: code breaking a rule in `CLAUDE.md`/`REVIEW.md`; lines in `CLAUDE.md`, `REVIEW.md`, or docs that this change makes untrue.
5. **Adversary**: the input, state, or ordering that makes this fail in production.

Finder brief (paste it):

> Report bugs: behaviour that is wrong now or will be. For each: `file`, `line`, `class` (kebab slug, e.g. `unchecked-optional`), `claim` (one sentence), `evidence` (code quoted from file:line in the worktree — read it; a guess from a name is not evidence), `sites` (every other file:line with the same class). Your scope is bugs; style, naming, formatting, lint/type errors CI catches, and refactor ideas belong to other tools. Return `[]` when you find nothing.

Done when every finder has returned.

## 5. Verify

Merge: the same class at the same site is one finding; union their `sites`. Drop anything on the posted list.

Spawn N verifiers in parallel (`quick` 1, `standard` 3, `deep` 5), each in fresh context with the bundle and the merged list, without the finders' reasoning. Each verifier opens the code in `$WT` and votes on every finding:
- `REAL`: the bug exists at head; quote the line that proves it. Add `introduced: yes|no`: is the bug absent at `$BASE`? (`git show $BASE:<file>`)
- `NOT_REAL`: wrong, intentional, or harmless. Also vote `NOT_REAL` when acting on the finding would push the author toward a harmful change.

Keep a finding when a strict majority votes `REAL`. It is pre-existing when a majority of those votes say `introduced: no`.

Done when every finding has N votes.

## 6. Tag

- **Important**: wrong behaviour, data loss, security, broken contract, or a `REVIEW.md` failure definition.
- **Pre-existing**: real, but present at `$BASE`, so the author did not cause it.
- **Nit**: real, low impact. Keep at most the nit cap, highest impact first.

Order: Important, Pre-existing, Nit. A class with several sites becomes one comment listing every site, so the author fixes the class rather than one line.

## 7. Report

Summary, first line a count:
```
2 Important · 1 Pre-existing · 1 Nit (round 2)
```
or `No issues found (round 1).` Then one line per finding: severity, `file:line`, claim.

Inline comment body:
```
**Important** · `unchecked-optional`
<claim> <evidence>
Also at: a.ts:12, b.ts:40
Fix it, or resolve this thread with the reason.
<!-- pr-review:finding file=src/a.ts class=unchecked-optional -->
```

Output by mode:
- `--json`: the array only.
- `--local`: the summary and findings, printed.
- Otherwise: post inline comments, then the summary ending with `<!-- pr-review:summary round=<r> sha=<head_sha> -->`.

Anchor inline only on lines in the diff: added lines, plus (GitLab) context lines given both `old_line` and `new_line`. Every other finding lives in the summary as `file:line`.

Finally `git worktree remove --force "$WT"`.

Done when the review is printed or visible in the PR/MR comments, and the worktree is gone.

## Platform commands

| Op | GitHub (`gh`) | GitLab (`glab`) |
|---|---|---|
| Fetch | `gh pr view <n> --json number,title,body,baseRefName,headRefOid` | `glab api projects/:id/merge_requests/<n>` → `title`, `description`, `target_branch`, `sha`, `diff_refs` |
| Earlier comments | `gh pr view <n> --json comments` + `gh api repos/{owner}/{repo}/pulls/<n>/comments --paginate` | `glab api projects/:id/merge_requests/<n>/discussions --paginate` |
| Inline | one review, see below | draft notes, then publish, see below |
| Summary | `gh pr comment <n> --body-file <file>` | `glab mr note <n> -m "<body>"` |

GitHub, one review for all inline comments (`side: LEFT` for a removed line):
```bash
gh api -X POST repos/{owner}/{repo}/pulls/<n>/reviews --input <review.json>
# {"commit_id":"<head_sha>","event":"COMMENT",
#  "comments":[{"path":"src/a.ts","line":12,"side":"RIGHT","body":"..."}]}
```

GitLab, one draft note per finding, then a single publish (one notification). SHAs come from `diff_refs`:
```bash
glab api -X POST projects/:id/merge_requests/<n>/draft_notes \
  -f note="<body>" -f 'position[position_type]=text' \
  -f "position[base_sha]=<base_sha>" -f "position[start_sha]=<start_sha>" -f "position[head_sha]=<head_sha>" \
  -f "position[new_path]=src/a.ts" -f "position[new_line]=12"
glab api -X POST projects/:id/merge_requests/<n>/draft_notes/bulk_publish
```
- Removed line: `old_path` + `old_line` only. Unchanged context line: both `old_line` and `new_line`.
- `draft_notes` returns 404 (older GitLab): POST each to `projects/:id/merge_requests/<n>/discussions` with `body=` and the same `position[...]` fields.
