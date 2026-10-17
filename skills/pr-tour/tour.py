#!/usr/bin/env python3
"""pr-tour helper, stdlib only.

  tour.py hunks BASE HEAD                                  list every changed hunk with a stable id
  tour.py threads URL                                      review threads of a GitHub PR / GitLab MR, as JSON
  tour.py render BASE HEAD STACKS [--threads F] [--url U]  check every hunk is in one changestack, print the tour
  tour.py post URL TOUR_FILE                               post the tour on the PR/MR, editing the earlier one
  tour.py serve BASE HEAD STACKS [--threads F] [--url U] [--title T] [--port P] [--no-open]
                                                           review the tour in a local web page and submit from it
"""
import argparse, hashlib, json, os, re, secrets, subprocess, sys, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)")
RISKS = ("high", "medium", "low")


def run(*cmd, input=None):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace", input=input).stdout


def git(*args):
    return run("git", "-c", "core.quotePath=false", *args)


def parse_diff(text):
    """{path: {"old": old path, "hunks": [[old_start, old_len, new_start, new_len, context, lines]]}},
    lines as (kind, old_no, new_no, text) with kind one of "+", "-", " "."""
    files, old, path, header, cur = {}, None, None, False, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            header, cur = True, None
        elif header and line.startswith("--- "):
            old = None if line == "--- /dev/null" else line[6:].rstrip("\t")
        elif header and line.startswith("+++ "):
            path = old if line == "+++ /dev/null" else line[6:].rstrip("\t")
        elif m := HUNK.match(line):
            header = False  # past the header, "--- x" is a removed line starting with "-- "
            a, b, c, d, ctx = m.groups()
            cur = [int(a), int(b or 1), int(c), int(d or 1), ctx.strip(), []]
            o, n = cur[0], cur[2]
            files.setdefault(path, {"old": old or path, "hunks": []})["hunks"].append(cur)
        elif cur is not None and line and line[0] in "+- ":
            k = line[0]
            cur[5].append((k, None if k == "+" else o, None if k == "-" else n, line[1:]))
            o, n = o + (k != "+"), n + (k != "-")
    return files


def changes(base, head):
    """Hunks in diff order as {id, path, hunk}; hunk is (old_start, old_len, new_start, new_len, context),
    or None for a file with no line changes (binary, mode, pure rename) so it still has to land in a changestack."""
    by_path = parse_diff(git("diff", "-U0", "--no-color", "--no-ext-diff", "-M", base, head))
    parts = git("diff", "--name-status", "-z", "-M", base, head).split("\0")
    out, i = [], 0
    while i < len(parts) - 1:
        n = 2 if parts[i][0] in "RC" else 1  # renames list old then new path
        for h in by_path.get(parts[i + n], {}).get("hunks") or [None]:
            out.append({"id": f"H{len(out) + 1}", "path": parts[i + n], "hunk": h and tuple(h[:5])})
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
    id isResolved isOutdated path line originalLine diffSide
    comments(first: 1) { nodes { databaseId author { login __typename } body url } } } } } } }"""


def target(url):
    """(platform, hostname, API path of the PR/MR) from its web URL."""
    u = urlparse(url.rstrip("/"))
    if "/-/merge_requests/" in u.path:
        project, n = u.path.strip("/").split("/-/merge_requests/")
        return "gitlab", u.hostname, f"projects/{quote(project, safe='')}/merge_requests/{n.split('/')[0]}"
    owner, repo, _, n = u.path.strip("/").split("/")[:4]
    return "github", u.hostname, f"repos/{owner}/{repo}/issues/{n}"


def threads(url):
    """Review threads; "id" is what resolving takes, "reply_to" is what replying takes."""
    platform, host, api = target(url)
    out = []
    if platform == "gitlab":
        for d in json_values(run("glab", "api", "--hostname", host, "--paginate", f"{api}/discussions")):
            first = d["notes"][0]
            if first.get("system") or not first.get("resolvable"):
                continue
            p, a = first.get("position") or {}, first["author"]
            out.append({
                "id": d["id"], "reply_to": d["id"],
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
    _, owner, repo, _, n = api.split("/")
    data = json.loads(run("gh", "api", "graphql", "--hostname", host, "-f", f"owner={owner}",
                          "-f", f"repo={repo}", "-F", f"n={n}", "-f", f"query={GH_THREADS}"))
    rt = data["data"]["repository"]["pullRequest"]["reviewThreads"]
    if rt["pageInfo"]["hasNextPage"]:
        print("warning: only the first 100 threads were fetched", file=sys.stderr)  # ponytail: paginate if PRs get that big
    for t in rt["nodes"]:
        c = t["comments"]["nodes"][0]
        a = c["author"] or {"login": "ghost", "__typename": "User"}
        out.append({
            "id": t["id"], "reply_to": c["databaseId"],
            "path": t["path"], "line": t["line"] or t["originalLine"],
            "side": "old" if t["diffSide"] == "LEFT" else "new",
            "author": a["login"], "bot": a["__typename"] != "User",
            "body": c["body"], "url": c["url"], "resolved": t["isResolved"], "outdated": t["isOutdated"],
        })
    return out


MARKER = "<!-- pr-tour -->"


def post(url, tour_file):
    """Edit the earlier tour comment (found by MARKER) or create one; print the comment URL."""
    platform, host, api = target(url)
    with open(tour_file) as f:
        body = f"{f.read().rstrip()}\n\n{MARKER}"
    cli = "glab" if platform == "gitlab" else "gh"
    path = f"{api}/notes" if platform == "gitlab" else f"{api}/comments"
    old = next((c for c in json_values(run(cli, "api", "--hostname", host, "--paginate", path))
                if MARKER in (c.get("body") or "")), None)
    if old is None:
        c = json.loads(run(cli, "api", "--hostname", host, "-X", "POST", path, "-f", f"body={body}"))
    elif platform == "gitlab":
        c = json.loads(run(cli, "api", "--hostname", host, "-X", "PUT", f"{path}/{old['id']}", "-f", f"body={body}"))
    else:  # GitHub edits issue comments by id, outside the PR's path
        c = json.loads(run(cli, "api", "--hostname", host, "-X", "PATCH",
                           f"{api.rsplit('/', 1)[0]}/comments/{old['id']}", "-f", f"body={body}"))
    print(c.get("html_url") or f"{url.rstrip('/')}#note_{c['id']}")


def excerpt(body):
    body = re.sub(r"<!--.*?-->|<[^>]+>", "", body, flags=re.S)
    for line in body.splitlines():
        if line := line.strip(" #>*_`"):
            return line[:100] + ("…" if len(line) > 100 else "")
    return ""


def place(t, hunks):
    """Changestack index of the hunk nearest the thread's line in the same file, or None."""
    best = None
    for si, h in hunks.get(t["path"], []):
        d = 0
        if h is not None and t["line"]:
            s, l = (h[2], h[3]) if t["side"] == "new" else (h[0], h[1])
            d = max(s - t["line"], 0, t["line"] - (s + max(l, 1) - 1))
        if best is None or d < best[0]:
            best = (d, si)
    return best and best[1]


def load(base, head, stacks_file, threads_file=None):
    """Check every hunk lands in exactly one changestack (exit 1 listing what doesn't), then return
    (hunks, changestacks, owner: hunk id -> changestack index, threads each with a "stack" index or None)."""
    hs = changes(base, head)
    by_id, by_path = {h["id"]: h for h in hs}, {}
    for h in hs:
        by_path.setdefault(h["path"], []).append(h["id"])
    with open(stacks_file) as f:
        stacks = json.load(f)["changestacks"]
    owner, errors = {}, []
    for si, st in enumerate(stacks):
        if not st.get("title") or st.get("risk") not in RISKS:
            errors.append(f"changestack {si + 1}: needs a title and risk in {RISKS}")
        visual = st.get("visual") or ""
        st["visual"] = visual = "\n".join(visual) if isinstance(visual, list) else visual
        if sum(line.lstrip().startswith("```") for line in visual.splitlines()) % 2:
            errors.append(f"changestack {si + 1}: visual has an unclosed ``` fence")
        for ref in st.get("hunks", []):
            ids = [ref] if ref in by_id else by_path.get(ref, [])
            if not ids:
                errors.append(f"changestack {si + 1}: unknown hunk id or path {ref!r}")
            for i in ids:
                if owner.get(i, si) != si:
                    errors.append(f"{i} is in changestacks {owner[i] + 1} and {si + 1}")
                owner[i] = si
    errors += [f"unstacked: {h['id']}  {h['path']}  {span(h['hunk'])}" for h in hs if h["id"] not in owner]
    if errors:
        sys.exit("\n".join(errors))
    ts = []
    if threads_file:
        with open(threads_file) as f:
            ts = json.load(f)
    placed = {}
    for h in hs:
        placed.setdefault(h["path"], []).append((owner[h["id"]], h["hunk"]))
    for t in ts:
        t["stack"] = place(t, placed)
    return hs, stacks, owner, ts


def render(base, head, stacks_file, threads_file=None, url=None):
    hs, stacks, owner, ts = load(base, head, stacks_file, threads_file)
    open_ = [t for t in ts if not t["resolved"]]
    bots = sum(t["bot"] for t in open_)
    print(f"{len(hs)} hunks in {len(stacks)} changestacks · {len(open_)} open threads "
          f"({bots} bot, {len(open_) - bots} human) · {len(ts) - len(open_)} resolved")

    def thread_line(t):
        where = f"{t['path']}:{t['line']}" if t["path"] else "general"
        tags = " (bot)" * t["bot"] + " (outdated)" * t["outdated"]
        return f"- {t['author']}{tags} at `{where}`: {excerpt(t['body'])} [thread]({t['url']})"

    for si, st in enumerate(stacks):
        print(f"\n## {si + 1}. {st['title']} · {st['risk']} risk")
        if st.get("why"):
            print(st["why"])
        if st["visual"]:
            print(f"\n{st['visual'].strip()}\n")
        files = {}
        for h in hs:
            if owner[h["id"]] == si:
                files.setdefault(h["path"], []).append(h["hunk"])
        for path, hunks in files.items():
            spans = [f"[{span(h)}]({link(url, path, h)})" if url else span(h) for h in hunks]
            print(f"- `{path}` {', '.join(spans)}")
        if mine := [t for t in open_ if t["stack"] == si]:
            print("\nOpen threads:")
            print("\n".join(thread_line(t) for t in mine))
    if elsewhere := [t for t in open_ if t["stack"] is None]:
        print("\n## Open threads outside the diff")
        print("\n".join(thread_line(t) for t in elsewhere))


def overlaps(h, full):
    """Does the -U0 hunk h fall inside the context hunk full, on either side?"""
    o, ol, n, nl, _ = h
    O, OL, N, NL = full[:4]
    return (n <= N + NL - 1 and n + max(nl, 1) - 1 >= N) or (o <= O + OL - 1 and o + max(ol, 1) - 1 >= O)


def web_data(base, head, stacks_file, threads_file, url, title):
    hs, stacks, owner, ts = load(base, head, stacks_file, threads_file)
    full = parse_diff(git("diff", "-U3", "--no-color", "--no-ext-diff", "-M", base, head))
    out = []
    for si, st in enumerate(stacks):
        files = {}
        for h in hs:
            if owner[h["id"]] != si:
                continue
            ctx = full.get(h["path"], {"old": h["path"], "hunks": []})
            f = files.setdefault(h["path"], {"path": h["path"], "old_path": ctx["old"], "hunks": [],
                                             "link": url and link(url, h["path"], None)})
            # ponytail: a context hunk spanning two changestacks shows in both; trim to own lines if it confuses
            for full_h in ctx["hunks"]:
                if h["hunk"] and overlaps(h["hunk"], full_h) and full_h[5] not in f["hunks"]:
                    f["hunks"].append(full_h[5])
        out.append({"title": st["title"], "risk": st["risk"], "why": st.get("why", ""), "visual": st["visual"],
                    "files": list(files.values())})
    for i, t in enumerate(ts):
        t["key"] = t.get("id") or f"t{i}"
    return {"pr": {"url": url, "title": title, "head": head, "base": base, "hunks": len(hs),
                   "platform": url and target(url)[0]}, "stacks": out, "threads": ts}


RESOLVE = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"


def submit(url, head, review):
    """Send a review built in the web page. review: {event: COMMENT|APPROVE|REQUEST_CHANGES, body,
    comments: [{id, path, old_path, line, old_line, body}], replies: [{id, thread, reply_to, body}], resolve: [thread id]}.
    Returns {"sent": [draft ids and thread ids that went out], "links": [...], "error"?}, so a failure midway
    tells the page what not to send twice."""
    platform, host, api = target(url)
    sent, links = [], []
    comments, replies = review.get("comments", []), review.get("replies", [])
    event, body = review.get("event", "COMMENT"), review.get("body", "").strip()
    try:
        if platform == "github":
            pulls = api.replace("/issues/", "/pulls/")
            gh = lambda *a, input=None: json.loads(run("gh", "api", "--hostname", host, *a, input=input) or "{}")
            if comments or body or event != "COMMENT":
                r = gh("-X", "POST", f"{pulls}/reviews", "--input", "-", input=json.dumps({
                    "commit_id": head, "event": event, "body": body,
                    "comments": [{"path": c["path"], "body": c["body"], "line": c["line"] or c["old_line"],
                                  "side": "RIGHT" if c["line"] else "LEFT"} for c in comments]}))
                sent += [c["id"] for c in comments]
                links.append(r.get("html_url"))
            for r in replies:
                links.append(gh("-X", "POST", f"{pulls}/comments/{r['reply_to']}/replies", "-f", f"body={r['body']}").get("html_url"))
                sent.append(r["id"])
            for t in review.get("resolve", []):
                gh("graphql", "-f", f"query={RESOLVE}", "-f", f"id={t}")
                sent.append(t)
        else:
            gl = lambda *a: json.loads(run("glab", "api", "--hostname", host, *a) or "{}")
            if comments:
                refs = gl(api)["diff_refs"]
                for c in comments:
                    pos = {"position_type": "text", "base_sha": refs["base_sha"], "start_sha": refs["start_sha"],
                           "head_sha": refs["head_sha"], "new_path": c["path"], "old_path": c["old_path"]}
                    pos |= {"new_line": c["line"]} if c["line"] else {}
                    pos |= {"old_line": c["old_line"]} if c["old_line"] else {}
                    gl("-X", "POST", f"{api}/draft_notes", "-f", f"note={c['body']}",
                       *[x for k, v in pos.items() for x in ("-f", f"position[{k}]={v}")])
                # ponytail: drafts created before a failure stay unpublished in GitLab; delete them there if one fails
                gl("-X", "POST", f"{api}/draft_notes/bulk_publish")
                sent += [c["id"] for c in comments]
            if body:
                gl("-X", "POST", f"{api}/notes", "-f", f"body={body}")
            for r in replies:
                gl("-X", "POST", f"{api}/discussions/{r['reply_to']}/notes", "-f", f"body={r['body']}")
                sent.append(r["id"])
            for t in review.get("resolve", []):
                gl("-X", "PUT", f"{api}/discussions/{t}", "-f", "resolved=true")
                sent.append(t)
            if event == "APPROVE":
                gl("-X", "POST", f"{api}/approve")
            links.append(url)
    except subprocess.CalledProcessError as e:
        return {"sent": sent, "links": [l for l in links if l], "error": (e.stderr or e.stdout or str(e)).strip()}
    return {"sent": sent, "links": [l for l in links if l]}


def serve(base, head, stacks_file, threads_file, url, title, port, open_browser):
    data = web_data(base, head, stacks_file, threads_file, url, title)
    token = secrets.token_urlsafe(24)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web.html")) as f:
        # token first: the data can itself contain "/*TOKEN*/" (a diff of this very file)
        page = f.read().replace("/*TOKEN*/", json.dumps(token), 1).replace("/*DATA*/", json.dumps(data).replace("<", "\\u003c"), 1)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, ctype="application/json"):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def allowed(self):
            # This server posts as the user, so only the page it served may call it: the Host check stops
            # DNS rebinding from reading the token, the token header stops other sites' forms and fetches.
            return self.headers.get("Host") in (f"127.0.0.1:{srv.server_port}", f"localhost:{srv.server_port}")

        def do_GET(self):
            if not self.allowed() or self.path.split("?")[0] != "/":
                return self.reply(404, '{"error": "not found"}')
            self.reply(200, page, "text/html; charset=utf-8")

        def do_POST(self):
            if not self.allowed() or self.path != "/submit" or self.headers.get("X-Tour-Token") != token:
                return self.reply(403, '{"error": "forbidden"}')
            if not url:
                return self.reply(400, '{"error": "range mode: no PR/MR to submit to"}')
            review = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            self.reply(200, json.dumps(submit(url, head, review)))

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    address = f"http://127.0.0.1:{srv.server_port}/"
    print(address, flush=True)
    if open_browser:
        webbrowser.open(address)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("hunks", "render", "serve"):
        s = sub.add_parser(name)
        s.add_argument("base")
        s.add_argument("head")
        if name != "hunks":
            s.add_argument("changestacks")
            s.add_argument("--threads")
            s.add_argument("--url")
    sub.choices["serve"].add_argument("--title", default="")
    sub.choices["serve"].add_argument("--port", type=int, default=0)
    sub.choices["serve"].add_argument("--no-open", action="store_true")
    sub.add_parser("threads").add_argument("url")
    s = sub.add_parser("post")
    s.add_argument("url")
    s.add_argument("tour_file")
    a = p.parse_args()
    url = getattr(a, "url", None) and a.url.rstrip("/")
    if a.cmd == "hunks":
        for h in changes(a.base, a.head):
            ctx = h["hunk"][4] if h["hunk"] else ""
            print(f"{h['id']}  {h['path']}  {span(h['hunk'])}  {ctx}".rstrip())
    elif a.cmd == "threads":
        print(json.dumps(threads(a.url), indent=1))
    elif a.cmd == "post":
        post(a.url, a.tour_file)
    elif a.cmd == "serve":
        serve(a.base, a.head, a.changestacks, a.threads, url, a.title, a.port, not a.no_open)
    else:
        render(a.base, a.head, a.changestacks, a.threads, url)


if __name__ == "__main__":
    main()
