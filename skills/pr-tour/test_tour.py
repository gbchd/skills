#!/usr/bin/env python3
"""Self-check for tour.py: python3 test_tour.py"""
import hashlib, json, os, subprocess, sys, tempfile

TOUR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tour.py")


def sh(*cmd, cwd, check=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


with tempfile.TemporaryDirectory() as d:
    git = lambda *a: sh("git", "-c", "user.name=t", "-c", "user.email=t@t", *a, cwd=d).stdout.strip()
    write = lambda p, s: open(os.path.join(d, p), "w").write(s)
    git("init", "-q")
    write("a.sql", "".join(f"line {i}\n" for i in range(1, 31)).replace("line 20\n", "-- comment\n"))
    write("old name.txt", "same\ncontent\nhere\n")
    write("gone.txt", "bye\n")
    git("add", "-A"); git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    write("a.sql", open(os.path.join(d, "a.sql")).read().replace("line 2\n", "line two\n").replace("-- comment\n", ""))
    git("mv", "old name.txt", "new name.txt")
    git("rm", "-q", "gone.txt")
    open(os.path.join(d, "img.bin"), "wb").write(bytes(range(256)))
    git("add", "-A"); git("commit", "-qm", "head")
    head = git("rev-parse", "HEAD")

    tour = lambda *a: sh(sys.executable, TOUR, *a, cwd=d, check=False)
    listing = tour("hunks", base, head).stdout
    print(listing)
    # the removed "-- comment" line must be read as a hunk line, not a "--- " file header
    assert listing.splitlines() == [
        "H1  a.sql  +2  line 1", "H2  a.sql  -20  line 19", "H3  gone.txt  -1",
        "H4  img.bin  no line changes", "H5  new name.txt  no line changes"], listing

    stacks = os.path.join(d, "s.json")
    json.dump({"changestacks": [
        {"title": "Wording", "risk": "low", "hunks": ["H1"], "visual": ["```diff", "-line 2", "+line two", "```"]},
        {"title": "Cleanup", "risk": "medium", "why": "check nothing reads these", "hunks": ["H2", "gone.txt", "img.bin", "new name.txt"]},
    ]}, open(stacks, "w"))
    threads = os.path.join(d, "t.json")
    json.dump([
        {"path": "a.sql", "line": 19, "side": "old", "author": "coderabbitai", "bot": True, "outdated": False,
         "body": "<!-- x -->\n_⚠️ Potential issue_\n\ndetails /*TOKEN*/ /*DATA*/", "url": "u1", "resolved": False},
        {"path": "a.sql", "line": 3, "side": "new", "author": "jun", "bot": False, "outdated": False,
         "body": "why?", "url": "u2", "resolved": False},
        {"path": "a.sql", "line": 3, "side": "new", "author": "jun", "bot": False, "outdated": False,
         "body": "done", "url": "u3", "resolved": True},
        {"path": None, "line": None, "side": "new", "author": "amy", "bot": False, "outdated": False,
         "body": "general", "url": "u4", "resolved": False},
    ], open(threads, "w"))

    r = tour("render", base, head, stacks, "--threads", threads, "--url", "https://github.com/o/r/pull/7/")
    print(r.stdout, r.stderr)
    assert r.returncode == 0
    assert r.stdout.startswith("5 hunks in 2 changestacks · 3 open threads (1 bot, 2 human) · 1 resolved")
    # the visual sits between the title and the file list, fences intact
    assert "## 1. Wording · low risk\n\n```diff\n-line 2\n+line two\n```\n\n- `a.sql`" in r.stdout
    sha = hashlib.sha256(b"a.sql").hexdigest()
    assert f"[+2](https://github.com/o/r/pull/7/files#diff-{sha}R2-R2)" in r.stdout
    assert f"[-20](https://github.com/o/r/pull/7/files#diff-{sha}L20-L20)" in r.stdout
    wording, cleanup = r.stdout.split("## 2. Cleanup")
    assert "jun at `a.sql:3`: why?" in wording and "u3" not in r.stdout
    assert "coderabbitai (bot) at `a.sql:19`: ⚠️ Potential issue [thread](u1)" in cleanup
    assert "## Open threads outside the diff\n- amy at `general`" in cleanup

    gl = tour("render", base, head, stacks, "--url", "https://gitlab.example.com/g/p/-/merge_requests/3")
    assert f"/-/merge_requests/3/diffs#{hashlib.sha1(b'a.sql').hexdigest()})" in gl.stdout

    json.dump({"changestacks": [
        {"title": "All", "risk": "low", "hunks": ["H1", "a.sql", "H9"], "visual": "```text\nunclosed"},
        {"title": "Dup", "risk": "nope", "hunks": ["H2"]}]}, open(stacks, "w"))
    r = tour("render", base, head, stacks)
    print(r.stderr)
    assert r.returncode == 1
    for msg in ["unknown hunk id or path 'H9'", "H2 is in changestacks 1 and 2", "changestack 2: needs a title and risk",
                "changestack 1: visual has an unclosed ``` fence",
                "unstacked: H3  gone.txt  -1", "unstacked: H5  new name.txt  no line changes"]:
        assert msg in r.stderr, msg

    # post: a fake gh lists $COMMENTS, logs every other call's args, answers with a comment
    bin_dir, log = os.path.join(d, "bin"), os.path.join(d, "gh.log")
    os.mkdir(bin_dir)
    fake = os.path.join(bin_dir, "gh")
    open(fake, "w").write(f'#!/bin/sh\ncase "$*" in *--paginate*) printf "%s\\n" "$COMMENTS";; '
                          f'*) printf "%s\\n" "$@" > {log}; echo \'{{"id": 9, "html_url": "h"}}\';; esac\n')
    os.chmod(fake, 0o755)
    write("tour.md", "# Tour\n")
    for comments, expect in [('[{"id": 1, "body": "hi"}][{"id": 5, "body": "old\\n<!-- pr-tour -->"}]',
                              ["PATCH", "repos/o/r/issues/comments/5"]),
                             ('[{"id": 1, "body": null}]', ["POST", "repos/o/r/issues/7/comments"])]:
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "COMMENTS": comments}
        r = subprocess.run([sys.executable, TOUR, "post", "https://github.com/o/r/pull/7", "tour.md"],
                           cwd=d, capture_output=True, text=True, env=env)
        assert r.returncode == 0 and r.stdout == "h\n", r.stderr
        args = open(log).read()
        assert all(e in args for e in expect) and "body=# Tour\n\n<!-- pr-tour -->" in args, args

    # submit: fake gh/glab log each call (argv + stdin) as a JSON line; FAIL=<text> fails calls containing it
    calls, sub_bin = os.path.join(d, "calls.log"), os.path.join(d, "bin2")
    os.mkdir(sub_bin)
    for cli in ("gh", "glab"):
        open(os.path.join(sub_bin, cli), "w").write(f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
stdin = sys.stdin.read() if "-" in args else ""
open({calls!r}, "a").write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
if os.environ.get("FAIL") and os.environ["FAIL"] in " ".join(args): sys.exit("boom")
mr = {{"diff_refs": {{"base_sha": "b", "start_sha": "s", "head_sha": "h"}}}}
print(json.dumps(mr if args[-1].endswith("merge_requests/3") else {{"html_url": "h"}}))
""")
        os.chmod(os.path.join(sub_bin, cli), 0o755)
    os.environ["PATH"] = f"{sub_bin}:{os.environ['PATH']}"
    sys.path.insert(0, os.path.dirname(TOUR))
    import tour

    def take_calls():
        lines = open(calls).read().splitlines() if os.path.exists(calls) else []
        open(calls, "w").close()
        return [json.loads(l) for l in lines]

    review = {"event": "REQUEST_CHANGES", "body": "see inline",
              "comments": [{"id": 1, "path": "a.sql", "old_path": "a.sql", "line": 2, "old_line": None, "body": "new side"},
                           {"id": 2, "path": "a.sql", "old_path": "a.sql", "line": None, "old_line": 20, "body": "old side"}],
              "replies": [{"id": 3, "thread": "T1", "reply_to": 55, "body": "ok"}], "resolve": ["T1"]}
    take_calls()
    res = tour.submit("https://github.com/o/r/pull/7", head, review)
    assert res == {"sent": [1, 2, 3, "T1"], "links": ["h", "h"]}, res
    c = take_calls()
    assert "repos/o/r/pulls/7/reviews" in c[0]["args"] and json.loads(c[0]["stdin"]) == {
        "commit_id": head, "event": "REQUEST_CHANGES", "body": "see inline",
        "comments": [{"path": "a.sql", "body": "new side", "line": 2, "side": "RIGHT"},
                     {"path": "a.sql", "body": "old side", "line": 20, "side": "LEFT"}]}, c[0]
    assert "repos/o/r/pulls/7/comments/55/replies" in c[1]["args"] and "body=ok" in c[1]["args"]
    assert "graphql" in c[2]["args"] and "id=T1" in c[2]["args"]

    # a failure midway reports what already went out and stops there
    os.environ["FAIL"] = "/replies"
    res = tour.submit("https://github.com/o/r/pull/7", head, review)
    del os.environ["FAIL"]
    assert res["sent"] == [1, 2] and "boom" in res["error"], res
    assert not any("graphql" in x["args"] for x in take_calls())

    api = "projects/g%2Fp/merge_requests/3"
    res = tour.submit("https://gitlab.example.com/g/p/-/merge_requests/3", head, {**review, "event": "APPROVE"})
    assert res["sent"] == [1, 2, 3, "T1"] and "error" not in res, res
    c = [x["args"] for x in take_calls()]
    assert [next(a for a in x if a.startswith(api)) for x in c] == [
        api, f"{api}/draft_notes", f"{api}/draft_notes", f"{api}/draft_notes/bulk_publish", f"{api}/notes",
        f"{api}/discussions/55/notes", f"{api}/discussions/T1", f"{api}/approve"], c
    assert {"position[new_line]=2", "position[head_sha]=h", "position[old_path]=a.sql"} <= set(c[1])
    assert not any("old_line" in a for a in c[1])
    assert "position[old_line]=20" in c[2] and not any("new_line" in a for a in c[2])

    # serve: the page carries the stacks with context lines; only the page itself may submit
    import re, urllib.error, urllib.request
    good = os.path.join(d, "good.json")
    json.dump({"changestacks": [
        {"title": "Wording", "risk": "low", "hunks": ["H1"]},
        {"title": "Cleanup", "risk": "medium", "hunks": ["H2", "gone.txt", "img.bin", "new name.txt"]}]}, open(good, "w"))
    srv = subprocess.Popen([sys.executable, TOUR, "serve", base, head, good, "--threads", threads,
                            "--url", "https://github.com/o/r/pull/7", "--title", "T", "--no-open"],
                           cwd=d, stdout=subprocess.PIPE, text=True)
    try:
        addr = srv.stdout.readline().strip()
        port = addr.rstrip("/").rsplit(":", 1)[1]

        def http(method, path, host=f"127.0.0.1:{port}", body=None, token=None):
            req = urllib.request.Request(addr.rstrip("/") + path, data=body, method=method, headers={
                "Host": host, "Content-Type": "application/json", **({"X-Tour-Token": token} if token else {})})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()

        status, page = http("GET", "/")
        assert status == 200
        token = re.search(r'const TOKEN = "([^"]+)";', page)[1]
        raw = re.search(r"const D = (.*?);\nconst TOKEN", page, re.S)[1]
        # a raw "<!--" or "<script" in the diff would make the parser swallow the page's own </script>
        assert "<" not in raw and "<!-- x -->" in json.dumps(json.loads(raw))
        assert "details /*TOKEN*/ /*DATA*/" in json.loads(raw)["threads"][0]["body"]
        data = json.loads(raw)
        wording, cleanup = data["stacks"]
        assert ["+", None, 2, "line two"] in wording["files"][0]["hunks"][0] and ["-", 2, None, "line 2"] in wording["files"][0]["hunks"][0]
        assert ["-", 20, None, "-- comment"] in cleanup["files"][0]["hunks"][0]
        assert [f["path"] for f in cleanup["files"]] == ["a.sql", "gone.txt", "img.bin", "new name.txt"]
        assert {t["author"]: t["stack"] for t in data["threads"]} == {"coderabbitai": 1, "jun": 0, "amy": None}

        assert http("GET", "/", host="evil.example")[0] == 404
        assert http("POST", "/submit", body=b"{}")[0] == 403
        assert http("POST", "/submit", body=b"{}", token="wrong")[0] == 403
        assert http("POST", "/submit", host=f"evil.example:{port}", body=b"{}", token=token)[0] == 403
        take_calls()
        status, out = http("POST", "/submit", token=token, body=json.dumps({"comments": review["comments"][:1]}).encode())
        assert status == 200 and json.loads(out)["sent"] == [1], out
        assert len(take_calls()) == 1
    finally:
        srv.terminate()
        srv.wait()

print("ok")
