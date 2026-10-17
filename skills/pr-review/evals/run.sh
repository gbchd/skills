#!/usr/bin/env bash
# Replays evals/cases.jsonl through /pr-review and scores recall + noise.
# Bug case:   {"repo":"/abs/path","base":"<sha>","head":"<sha>","file":"src/a.ts","line":42}
# Clean case: same without file/line — any Important finding counts as a false positive.
# Usage: evals/run.sh [quick|standard|deep]   (needs jq)
set -euo pipefail

depth=${1:-standard}
cases="$(dirname "$0")/cases.jsonl"
hits=0 bugs=0 fps=0 cleans=0

while IFS= read -r c; do
  [ -z "$c" ] && continue
  repo=$(jq -r .repo <<<"$c"); base=$(jq -r .base <<<"$c"); head=$(jq -r .head <<<"$c")
  file=$(jq -r '.file // empty' <<<"$c"); line=$(jq -r '.line // 0' <<<"$c")

  # </dev/null: otherwise claude eats the rest of cases.jsonl from the loop's stdin
  out=$(cd "$repo" && claude -p "/pr-review $base..$head $depth --json" \
    --allowedTools 'Bash(git:*),Bash(mktemp:*),Read,Grep,Glob,Agent,Skill' </dev/null) || out='[]'
  findings=$(sed '/^```/d' <<<"$out" | jq -c 'if type == "array" then . else [] end' 2>/dev/null || echo '[]')

  if [ -n "$file" ]; then
    bugs=$((bugs + 1))
    hit=$(jq --arg f "$file" --argjson l "$line" \
      'any(.[]; .file == $f and ((.line - $l) | if . < 0 then -. else . end) <= 10)' <<<"$findings")
    [ "$hit" = true ] && hits=$((hits + 1))
    echo "bug   $repo $head $file:$line -> $hit"
  else
    cleans=$((cleans + 1))
    n=$(jq '[.[] | select(.severity == "Important")] | length' <<<"$findings")
    fps=$((fps + n))
    echo "clean $repo $head -> $n important"
  fi
done <"$cases"

echo "recall: $hits/$bugs   false positives: $fps across $cleans clean cases   depth: $depth"
