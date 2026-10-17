# Skills repo

Agent skills, shipped as a Claude Code plugin (`.claude-plugin/`).

## Adding a skill

- One folder per skill: `skills/<name>/SKILL.md`. The folder name must match the `name` in frontmatter (kebab-case).
- Frontmatter needs `name` and `description`. The description is what the agent matches on: say what it does and when to use it.
- Supporting files (references, scripts) go next to `SKILL.md` and are linked from it by relative path.
- Skills are auto-discovered from `skills/`; no manifest edits needed.
- Add the skill to the table in `README.md`.
- Every user-facing change ships with a changeset: `npx changeset` (patch = fix/wording, minor = new or changed skill, major = removed/renamed skill). Never edit `version` by hand; merging the "chore: version skills" PR bumps `package.json` + `plugin.json`, writes `CHANGELOG.md`, and creates the release.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `<type>(<scope>): <summary>`.

- Types: `feat`, `fix`, `docs`, `refactor`, `chore`, `ci`, `build`, `test`, `perf`, `style`, `revert`.
- Scope is the skill name when the change touches one skill (`feat(tdd): ...`), otherwise omit it or use the area (`ci`, `plugin`).
- Summary: imperative, lowercase, no trailing period, under 72 chars.
- Breaking change (removed or renamed skill): add `!` after the type/scope (`feat(tdd)!: ...`) and a `BREAKING CHANGE:` footer.
- PR titles follow the same format.
