---
name: release-workflow
description: How to cut a release of the xberg-io/actions repo — clean-tree + poly/tests preconditions, CHANGELOG rollover, commit and push to main, then the two-tag scheme this repo uses (create a NEW immutable `vX.Y.Z` annotated tag AND force-move the floating major `v1` tag to the same commit so every consumer pinning `@v1` picks up the release). Load when cutting/releasing a new version of the actions repo, or when the floating `v1` tag needs to be advanced.
---

# Release workflow (xberg-io/actions)

This repo publishes reusable composite actions and workflows consumed by every other xberg-io repo as `uses: xberg-io/actions/<action>@v1` and `uses: xberg-io/actions/.github/workflows/<wf>.yml@v1`. Consumers pin the **floating major tag `v1`**, so a release is only visible to them once `v1` is moved to the new commit.

## Tag scheme

- **Immutable version tags** — `vX.Y.Z` (annotated). Never re-pointed once pushed. Latest at time of writing: `v1.8.102`. History runs `v1.0.0 → v1.8.10x`.
- **Floating major tag** — `v1` (annotated). Deliberately force-updated on every release to point at the newest release commit. This is the ref consumers pin.

Both are annotated tag objects (`git cat-file -t v1` → `tag`), so create/move them with `-a`.

## Preconditions (must pass before releasing)

Run from a clean checkout of `main`:

```bash
git switch main
git fetch origin
git status --porcelain            # must be EMPTY — no uncommitted/untracked changes
git log --oneline origin/main -1  # confirm local main == remote tip

poly fmt --check .                # formatting clean
poly lint .                       # lint clean (also: task lint)
task test                         # unit tests — runs `uv run pytest -v` across configured testpaths
```

Do not proceed if the tree is dirty or any check fails. `task validate` (== `task lint`) runs actionlint + shellcheck + shfmt via poly; the action test workflows in `.github/workflows/test-*.yml` are the CI gate — they must be green on `main`.

## 1. Roll the CHANGELOG and commit

`CHANGELOG.md` is hand-maintained with a `## [Unreleased]` section. Move the accumulated `Unreleased` entries under a new dated version heading:

```markdown
## [Unreleased]

## [v1.8.103] - 2026-07-22

### Added
- ... (entries that were under Unreleased)
```

Then commit and push the release commit to `main` (direct commit if you have rights, otherwise land it via PR and pull the merged `main`):

```bash
git add CHANGELOG.md
git commit -m "chore(release): v1.8.103"
git push origin main
```

Re-run `git fetch origin && git log --oneline origin/main -1` and make sure local `main` is exactly the commit you just pushed — the tags below must point at the **pushed** release commit.

## 2. Create the new immutable version tag (AFTER pushing)

Pick the next version by bumping the latest `v1.Y.Z` (patch for fixes, minor for new actions/inputs). Create it at the release commit and push it:

```bash
git tag -a v1.8.103 -m "v1.8.103"   # tags current HEAD (the pushed release commit)
git push origin v1.8.103
```

## 3. Move the floating major tag `v1` to the new release

Force-update `v1` to point at the same commit/tag, then force-push the `v1` ref so `@v1` consumers pick up the release:

```bash
git tag -f -a v1 -m "v1 -> v1.8.103" v1.8.103   # re-point annotated v1 at the new version tag
git push origin v1 --force
```

`git tag -f v1 <ref>` + `git push origin v1 --force` is the established method for advancing the floating major. `<ref>` can be the new version tag (`v1.8.103`) or the release commit SHA — both resolve to the same commit.

> This force-update is a **deliberate, expected tag move**, not a branch force-push — it is the one sanctioned exception to the repo's "never force-push" rule, and it only ever touches the `v1` tag ref (never a branch). If you prefer the lease-guarded variant, `git push origin v1 --force-with-lease` also works for the tag ref. Never force-move any `vX.Y.Z` immutable tag.

## 4. Verify

```bash
git fetch origin --tags --force
git rev-parse v1                  # must equal:
git rev-parse v1.8.103            # ... the new version tag / release commit
```

Both must resolve to the release commit. Consumers pinning `@v1` now resolve to `v1.8.103`.
