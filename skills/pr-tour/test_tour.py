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
         "body": "<!-- x -->\n_⚠️ Potential issue_\n\ndetails", "url": "u1", "resolved": False},
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

print("ok")
