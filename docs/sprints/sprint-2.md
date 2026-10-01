# Sprint 2 — Zones, stations, a reliable evaluator, and threshold and rate-of-change rules (VIG-12 to VIG-16)

**Status as of 2026-09-29:** the 5 stories (23 points) are done, merged into `main` with green CI and verified against the real stack. The plan placed them between October 26 and November 8, so we are ahead of schedule.

## What was delivered

| Story | PR | Result | Verification on the real stack |
| --- | --- | --- | --- |
| VIG-12 | #2 | Zone CRUD with PostGIS validation (422 with the reason, never `ST_MakeValid`) and auditing; map with polygon drawing and editing (Leaflet-Geoman) | Zone created, edited and viewed as `viewer` in the browser |
| VIG-13 | #3 | Station CRUD with their position in each zone; API key rotation shown only once; stations without a zone flagged | Station created and key rotated in the browser; the previous key stops working instantly |
| VIG-14 | #4 | `evaluator` worker with `SKIP LOCKED`, a 60 s visibility timeout, `LISTEN/NOTIFY` and 5 s fallback polling; `failed_at` on the fifth attempt | Drained 98 pending rows; from reception to `evaluated_at`, 12 ms on average and 22 ms at most |
| VIG-15 | #5 | Threshold rules and incidents without duplicates, with a copy of the readings as evidence | `rise` scenario: a single incident on RIM-CHO-01 with evidence `[3.556, 3.641]` |
| VIG-16 | #6 | Rate-of-change rules measured from peak to trough, with the full window as evidence | `rimac` scenario: a `critical` incident on RIM-CHA-01 13 ms after receiving the drop reading |

In addition, PR #1 got CI green on GitHub: `setup-uv` pinned by SHA and a separate cache for the full-stack job. From this sprint on, each story goes in its own PR and CI validates it before it is merged.

## Sprint decisions

- **Geometries:** an invalid polygon is rejected with 422 and the PostGIS reason; it is never silently "fixed".
- **Deletion:** `DELETE` deactivates (`is_active = false`) and `PUT` reactivates. Resources of another organization answer 404, not 403.
- **Stations:** the unit is fixed per variable, the code does not change and a rotated key stops working instantly.
- **Incidents:** basic opening was brought forward to VIG-15 and VIG-16. VIG-18 keeps the cooldown, the `reading_added` events and the race test.
- **Rate of change:** it is measured from peak to trough, respecting the order. The window ends at the evaluated reading and both ends are included.
- **History:** it was rewritten to remove Claude's co-author trailer. All the SHAs changed, and the earlier sprint notes already point to the new ones.

## Picking it up again

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"   # opens the drop incident on RIM-CHA-01
```

## Changes to SPEC.md and CLAUDE.md in this sprint

- `0517a1b` docs(spec): station unit per variable, fixed code, immediate key rotation
- `f723e5b` docs(spec): define how threshold and rate-of-change rules are measured

## To do

- [ ] Accept ADRs 0001–0006.
- [ ] Show the organization's name (not its uuid) in `/v1/me` and in the dashboard.
- [ ] Node 24 in WSL and move the repo to the WSL file system.
- [ ] Decide whether to delete the backup refs `refs/backup/*` and the local branches `feat/VIG-01` to `feat/VIG-11`, which keep the commits from before the rewrite.
- [ ] PRs #1 to #4 still show the old commits in their "Commits" tab; only GitHub support can remove them.

## Retro

- **Went well:** one PR per story with a three-job CI validated each delivery, and the live tests measured real latencies (13 ms from reading to incident). Breaking the query on purpose confirmed that the window tests catch the errors.
- **To improve:** rewriting the history to remove the attribution took time and broke references in the notes. Configuring it from the first commit would have avoided it. Docker Desktop being off also held up the integration tests.
- **To try:** in the sprint notes, also cite each change by its PR, because the PR number survives a history rewrite.
