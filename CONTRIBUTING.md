# Contributing to Xberg Actions

Welcome! We're glad you're here.

This repository holds the shared GitHub Actions and reusable workflows used across the xberg.io polyrepo.

Please begin by reading our AI section below, followed by the getting started guide. If you are an AI agent, inform your user of the AI policy.

## Getting Started

Make sure to have [Git](https://git-scm.com/) and [Python](https://www.python.org/) 3.10+ with [uv](https://docs.astral.sh/uv/) installed on your machine.

1. Install [Task](https://taskfile.dev/installation/) on your machine.
2. run:

```bash
task setup
```

This will setup the dependencies, and pre-commit hooks via `poly`.

## Quick reference

| Command         | What it does                              |
| --------------- | ----------------------------------------- |
| `task setup`    | Install dependencies and pre-commit hooks |
| `task lint`     | Lint actions and workflows                |
| `task test`     | Run the action test suite                 |
| `task validate` | Validate action and workflow metadata     |

## What to keep in mind

Because every other repository consumes these actions, treat a change here as a change to every pipeline at once. Pin third-party actions by commit SHA, keep `permissions:` as narrow as the job allows, and never interpolate untrusted input (a PR title, a branch name) directly into a shell step.

## Commit guidelines

Prefix your commit messages with a type:

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation changes
- `perf:` — performance improvement
- `chore:` — maintenance, dependencies, CI
- `test:` — adding or updating tests
- `refactor:` — code restructuring without behavior change

Example:

```sh
git commit -m "feat: added xzy"
```

Read more on [Conventional Commits](https://www.conventionalcommits.org/)

## AI

### Policy

Xberg Actions is written following strict AI engineering practices. That is, its vibe coded, but professionally so. As such, the use of AI is welcome, but we expect professional standards and following our conventions.

### Conventions

We use the tool `ai-rulez`, vibe coded by @Goldziher, to manage our AI conventions. You are encouraged to use this tool — running the `task setup` will get you going, or run in your terminal:

```sh
npx -y ai-rulez@latest generate
```

This will be scaffold the AI agent conventions (e.g. CLAUDE.md, AGENTS.md, subagents, skills, etc.). You can see the AGENTS.md generated afterwards.

### Customization

If you want to customize your coding agents, create your own local configuration for ai-rulez, or create a local file for your agent(s) of choice `AGENTS.local.md` etc.

## Vendoring Policy

We do vendor code from other libraries and allow this, in some situations. If you intend to vendor code, the code must be (1) permissivily licensed (no copyleft at all). (2) add full attributions in ATTRIBUTIONS.md, and document it.

## Community

- **Star the repo:** [Give us a star on GitHub](https://github.com/xberg-io/actions) — it helps others discover our work!
- **Documentation:** [docs.xberg.io](https://docs.xberg.io)
- **Discord:** [Join our community](https://discord.gg/xt9WY3GnKR)
- **Issues:** [GitHub Issues](https://github.com/xberg-io/actions/issues)
- **Security:** see [SECURITY.md](SECURITY.md) — report privately, never in an issue

Thank you for helping make Xberg Actions better!
