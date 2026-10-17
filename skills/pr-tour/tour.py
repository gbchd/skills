#!/usr/bin/env python3
"""pr-tour helper, stdlib only.

  tour.py hunks BASE HEAD                                  list every changed hunk with a stable id
  tour.py threads URL                                      review threads of a GitHub PR / GitLab MR, as JSON
  tour.py render BASE HEAD GROUPS [--threads F] [--url U]  check every hunk is grouped once, print the tour
"""
import argparse, hashlib, json, re, subprocess, sys
from urllib.parse import quote, urlparse

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)")
RISKS = ("high", "medium", "low")


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace").stdout


def git(*args):
    return run("git", "-c", "core.quotePath=false", *args)


def changes(base, head):
    """Hunks in diff order as {id, path, hunk}; hunk is (old_start, old_len, new_start, new_len, context),
    or None for a file with no line changes (binary, mode, pure rename) so it still has to be grouped."""
    by_path, old, path, header = {}, None, None, False
    for line in git("diff", "-U0", "--no-color", "--no-ext-diff", "-M", base, head).splitlines():
        if line.startswith("diff --git "):
            header = True
        elif header and line.startswith("--- "):
            old = None if line == "--- /dev/null" else line[6:].rstrip("\t")
        elif header and line.startswith("+++ "):
            path = old if line == "+++ /dev/null" else line[6:].rstrip("\t")
        elif m := HUNK.match(line):
            header = False  # past the header, "--- x" is a removed line starting with "-- "
            a, b, c, d, ctx = m.groups()
            by_path.setdefault(path, []).append((int(a), int(b or 1), int(c), int(d or 1), ctx.strip()))
    parts = git("diff", "--name-status", "-z", "-M", base, head).split("\0")
    out, i = [], 0
    while i < len(parts) - 1:
        n = 2 if parts[i][0] in "RC" else 1  # renames list old then new path
        for h in by_path.get(parts[i + n]) or [None]:
            out.append({"id": f"H{len(out) + 1}", "path": parts[i + n], "hunk": h})
        i += n + 1
    return out


def span(h):
    if h is None:
        return "no line changes"
    o, ol, n, nl, _ = h
    s, l, sign = (n, nl, "+") if nl else (o, ol, "-")
    return f"{sign}{s}" if l == 1 else f"{sign}{s}-{s + l - 1}"


def link(url, path, h):
    if "/-/merge_requests/" in url:
        # ponytail: file anchor only; GitLab line anchors need old/new line pairs, add if people miss them
        return f"{url}/diffs#{hashlib.sha1(path.encode()).hexdigest()}"
    a = f"{url}/files#diff-{hashlib.sha256(path.encode()).hexdigest()}"
    if h is None:
        return a
    o, ol, n, nl, _ = h
    return a + (f"R{n}-R{n + nl - 1}" if nl else f"L{o}-L{o + ol - 1}")


def json_values(s):
    """Parse one JSON array or several back to back (paginated CLI output), flattened."""
    dec, i, out = json.JSONDecoder(), 0, []
    while (i := len(s) - len(s[i:].lstrip())) < len(s):
        v, i = dec.raw_decode(s, i)
        out.extend(v if isinstance(v, list) else [v])
    return out


GH_THREADS = """query($owner: String!, $repo: String!, $n: Int!) { repository(owner: $owner, name: $repo) {
  pullRequest(number: $n) { reviewThreads(first: 100) { pageInfo { hasNextPage } nodes {
    isResolved isOutdated path line originalLine diffSide
    comments(first: 1) { nodes { author { login __typename } body url } } } } } } }"""


def threads(url):
    u = urlparse(url.rstrip("/"))
    out = []
    if "/-/merge_requests/" in u.path:
        project, n = u.path.strip("/").split("/-/merge_requests/")
        raw = run("glab", "api", "--hostname", u.hostname, "--paginate",
                  f"projects/{quote(project, safe='')}/merge_requests/{n.split('/')[0]}/discussions")
        for d in json_values(raw):
            first = d["notes"][0]
            if first.get("system") or not first.get("resolvable"):
                continue
            p, a = first.get("position") or {}, first["author"]
            out.append({
                "path": p.get("new_path") or p.get("old_path"),
                "line": p.get("new_line") or p.get("old_line"),
                "side": "old" if p.get("old_line") and not p.get("new_line") else "new",
                "author": a["username"],
                # ponytail: name heuristic, GitLab bots are often plain users; add a bot list if it misfires
                "bot": bool(a.get("bot")) or "bot" in a["username"].lower() or a["username"] == "GitLabDuo",
                "body": first["body"],
                "url": f"{url.rstrip('/')}#note_{first['id']}",
                "resolved": all(x.get("resolved") for x in d["notes"] if x.get("resolvable")),
                "outdated": False,
            })
        return out
    owner, repo, _, n = u.path.strip("/").split("/")[:4]
    data = json.loads(run("gh", "api", "graphql", "--hostname", u.hostname, "-f", f"owner={owner}",
                          "-f", f"repo={repo}", "-F", f"n={n}", "-f", f"query={GH_THREADS}"))
    rt = data["data"]["repository"]["pullRequest"]["reviewThreads"]
    if rt["pageInfo"]["hasNextPage"]:
        print("warning: only the first 100 threads were fetched", file=sys.stderr)  # ponytail: paginate if PRs get that big
    for t in rt["nodes"]:
        c = t["comments"]["nodes"][0]
        a = c["author"] or {"login": "ghost", "__typename": "User"}
        out.append({
            "path": t["path"], "line": t["line"] or t["originalLine"],
            "side": "old" if t["diffSide"] == "LEFT" else "new",
            "author": a["login"], "bot": a["__typename"] != "User",
            "body": c["body"], "url": c["url"], "resolved": t["isResolved"], "outdated": t["isOutdated"],
        })
    return out


def excerpt(body):
    body = re.sub(r"<!--.*?-->|<[^>]+>", "", body, flags=re.S)
    for line in body.splitlines():
        if line := line.strip(" #>*_`"):
            return line[:100] + ("…" if len(line) > 100 else "")
    return ""


def place(t, hunks):
    """Group index of the hunk nearest the thread's line in the same file, or None."""
    best = None
    for gi, h in hunks.get(t["path"], []):
        d = 0
        if h is not None and t["line"]:
            s, l = (h[2], h[3]) if t["side"] == "new" else (h[0], h[1])
            d = max(s - t["line"], 0, t["line"] - (s + max(l, 1) - 1))
        if best is None or d < best[0]:
            best = (d, gi)
    return best and best[1]


def render(base, head, groups_file, threads_file=None, url=None):
    hs = changes(base, head)
    by_id, by_path = {h["id"]: h for h in hs}, {}
    for h in hs:
        by_path.setdefault(h["path"], []).append(h["id"])
    with open(groups_file) as f:
        groups = json.load(f)["groups"]
    owner, errors = {}, []
    for gi, g in enumerate(groups):
        if not g.get("title") or g.get("risk") not in RISKS:
            errors.append(f"group {gi + 1}: needs a title and risk in {RISKS}")
        for ref in g.get("hunks", []):
            ids = [ref] if ref in by_id else by_path.get(ref, [])
            if not ids:
                errors.append(f"group {gi + 1}: unknown hunk id or path {ref!r}")
            for i in ids:
                if owner.get(i, gi) != gi:
                    errors.append(f"{i} is in groups {owner[i] + 1} and {gi + 1}")
                owner[i] = gi
    errors += [f"ungrouped: {h['id']}  {h['path']}  {span(h['hunk'])}" for h in hs if h["id"] not in owner]
    if errors:
        sys.exit("\n".join(errors))

    ts = []
    if threads_file:
        with open(threads_file) as f:
            ts = json.load(f)
    open_ = [t for t in ts if not t["resolved"]]
    placed = {}
    for h in hs:
        placed.setdefault(h["path"], []).append((owner[h["id"]], h["hunk"]))
    per_group, elsewhere = {}, []
    for t in open_:
        gi = place(t, placed)
        (elsewhere if gi is None else per_group.setdefault(gi, [])).append(t)

    bots = sum(t["bot"] for t in open_)
    print(f"{len(hs)} hunks in {len(groups)} groups · {len(open_)} open threads "
          f"({bots} bot, {len(open_) - bots} human) · {len(ts) - len(open_)} resolved")

    def thread_line(t):
        where = f"{t['path']}:{t['line']}" if t["path"] else "general"
        tags = " (bot)" * t["bot"] + " (outdated)" * t["outdated"]
        return f"- {t['author']}{tags} at `{where}`: {excerpt(t['body'])} [thread]({t['url']})"

    for gi, g in enumerate(groups):
        print(f"\n## {gi + 1}. {g['title']} · {g['risk']} risk")
        if g.get("why"):
            print(g["why"])
        files = {}
        for h in hs:
            if owner[h["id"]] == gi:
                files.setdefault(h["path"], []).append(h["hunk"])
        for path, hunks in files.items():
            spans = [f"[{span(h)}]({link(url, path, h)})" if url else span(h) for h in hunks]
            print(f"- `{path}` {', '.join(spans)}")
        if gi in per_group:
            print("\nOpen threads:")
            print("\n".join(thread_line(t) for t in per_group[gi]))
    if elsewhere:
        print("\n## Open threads outside the diff")
        print("\n".join(thread_line(t) for t in elsewhere))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("hunks", "render"):
        s = sub.add_parser(name)
        s.add_argument("base")
        s.add_argument("head")
    sub.choices["render"].add_argument("groups")
    sub.choices["render"].add_argument("--threads")
    sub.choices["render"].add_argument("--url")
    sub.add_parser("threads").add_argument("url")
    a = p.parse_args()
    if a.cmd == "hunks":
        for h in changes(a.base, a.head):
            ctx = h["hunk"][4] if h["hunk"] else ""
            print(f"{h['id']}  {h['path']}  {span(h['hunk'])}  {ctx}".rstrip())
    elif a.cmd == "threads":
        print(json.dumps(threads(a.url), indent=1))
    else:
        render(a.base, a.head, a.groups, a.threads, a.url and a.url.rstrip("/"))


if __name__ == "__main__":
    main()
