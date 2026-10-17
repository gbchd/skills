# Skills

My agent skills for Claude Code and any agent that reads `SKILL.md`.

## Install

<details>
<summary><strong>Claude Code</strong></summary>

```bash
claude plugin marketplace add gbchd/skills
claude plugin install gbchd-skills@gbchd
```

</details>

<details>
<summary><strong>Any other agent</strong> (copies editable files)</summary>

```bash
npx skills@latest add gbchd/skills
```

</details>

## Skills

| Skill | What it does |
| --- | --- |
| [explain](./skills/explain/SKILL.md) | Explain one slice of the codebase before you change it, grounded in the code as it is today. |
| [pr-review](./skills/pr-review/SKILL.md) | Review a GitHub PR or GitLab MR with parallel bug finders, majority-vote verification, and round limits that make review converge. |
| [pr-tour](./skills/pr-tour/SKILL.md) | Tour a GitHub PR or GitLab MR for a human reviewer: the diff cut into changestacks in reading order, each with risk, a diagram or pseudocode, diff links, and its open threads. |

## Local development

```bash
claude --plugin-dir .
```

See [AGENTS.md](./AGENTS.md) for how to add a skill.

## License

[MIT](./LICENSE)
