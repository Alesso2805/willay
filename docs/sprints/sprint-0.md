# Sprint 0 — Foundations (VIG-01 to VIG-05)

**Status as of 2026-09-26:** stories done and verified locally. CI on GitHub is still missing (there is no remote).

## Where the code stands

The branches are **stacked**: each one starts from the previous one. `main` only has the `docs(spec)` commits.

```
main → feat/VIG-01-monorepo-ci → feat/VIG-02-docker-compose
     → feat/VIG-03-initial-migration → feat/VIG-04-seed → feat/VIG-05-adrs  (the most recent)
```

To pick it up again: `git checkout feat/VIG-05-adrs`. `git log --oneline main..HEAD` lists the 8 commits of the sprint.

## Changes to the specification in this sprint

`71e637f`, `7cea26e`, `fe25e48`, `515d115`, `7896ba9` (see `git log -- docs/SPEC.md`).

## Retro

- **Went well:** verifying against the real stack uncovered three false assumptions in time: the claim format, Keycloak's default scopes and the order of the privileges.
- **To try:** open one PR per story as soon as the remote exists, instead of stacking branches.
