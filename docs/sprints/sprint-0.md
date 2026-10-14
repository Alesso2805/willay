# Sprint 0 — Foundations (VIG-01 to VIG-05)

**Status as of 2026-09-26:** stories done and verified locally. CI on GitHub is still missing (there is no remote).

## Where the code stands

The branches are **stacked**: each one starts from the previous one. `main` only has the `docs(spec)` commits.

```
main → feat/VIG-01-monorepo-ci → feat/VIG-02-docker-compose
     → feat/VIG-03-initial-migration → feat/VIG-04-seed → feat/VIG-05-adrs  (the most recent)
```

To pick it up again: `git checkout feat/VIG-05-adrs`. `git log --oneline main..HEAD` lists the 8 commits of the sprint.

## Quick check (from WSL)

```bash
make up         # 11 services: all healthy and migrate in Exited (0)
make seed       # keys in .secrets/station-keys.json
make lint test  # Ruff, Mypy, ESLint; Pytest (37) and Vitest (3)
make down       # when you are done
```

## To do before Sprint 1

- [ ] Create the repo on GitHub, push and merge the branches in order (or open one PR per story). Confirm CI is green.
- [ ] Decide whether to align the coding agent's instructions with SPEC: the `organization` claim is an object `{alias: {id}}`, and the roles and extensions live in the Postgres init.
- [ ] Review ADRs 0001–0006 and move them to "Accepted".
- [ ] Install Node 24 in WSL (`nvm install` reads `dashboard/.nvmrc`).

## Next step

Plan Sprint 1 starting with **VIG-06** (OIDC login and tenant resolution with 403 for zero or several organizations). In parallel, **VIG-08** (`POST /v1/readings`), which already has the format and the hash of the API keys in `ingestion/infrastructure/api_keys.py`.

## Changes to SPEC.md in this sprint

`71e637f`, `7cea26e`, `fe25e48`, `515d115`, `7896ba9` (see `git log -- docs/SPEC.md`).

## Retro

- **Went well:** verifying against the real stack uncovered three false assumptions in time: the claim format, Keycloak's default scopes and the order of the privileges.
- **To improve:** working on `/mnt/c` from Windows caused CRLF and path conversion problems. It is better to clone the repo inside WSL.
- **To try:** open one PR per story as soon as the remote exists, instead of stacking branches.
