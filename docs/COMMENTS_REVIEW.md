# Comments left for review

The comment cleanup of October 2026 (branch `chore/comment-cleanup`) changed only comments that were clearly redundant, decorative or out of date. These are the ones where removing or rewriting them depends on a decision that is not the cleanup's to make. Each entry says where the comment is, what is unclear, and what I would do.

## The minimum station interval and its comment

`backend/src/willay/territory/domain/stations.py:20`

```python
# The silence detector runs every 15 s: shorter intervals add nothing.
MIN_INTERVAL_S = 5
```

The comment argues for a 15 s minimum, but the value is 5 s and has been since the first version. With the default K = 3, a 5 s interval gives a 15 s silence threshold, one detector cycle, which may be what was meant. With K = 1 (the minimum multiplier) it gives 5 s, which the detector can notice up to 15 s late (still within SPEC's K × interval + 30 s). Either the comment should explain why 5 s, or the minimum should change, and changing the minimum is a product decision (SPEC: stations, expected interval).

**What I would do:** keep 5 s and write "The silence detector runs every 15 s: at the default K = 3, 5 s is already one cycle, so a shorter interval adds nothing."

## A worker helper nobody uses

`backend/src/willay/workers/_runner.py:85`

```python
def run_worker(name: str, interval_s: float, tick: Tick = _noop) -> None:
    """Simple workers (no wakeup notifications yet): one tick every `interval_s`."""
```

No code calls `run_worker`: every worker, including the polling-only ones (silence, escalation, demo), uses `run_async_worker` with `run_loop`. The "yet" in its docstring is stale, but the real question is whether the function should exist. Removing it is a code change, outside a comment-only cleanup.

**What I would do:** delete the function in its own `refactor:` commit, with its docstring.

## Labelled dashed separators

- `backend/src/willay/seed/data.py:110, 125, 163, 199, 227, 253` (for example `# --- Zones -----…`)
- `backend/tests/unit/test_ingestion.py:35, 84, 146` (for example `# --- domain -----…`)

The cleanup removes decorative separators, but these carry a title that groups a long file: the seed's organizations, zones, stations, contacts, policies and rules, and the test file's three layers. The counts in the seed's titles (7 Rímac + 3 isolation stations, 4 + 1 contacts, 5 + 1 rules) were checked and are right.

**What I would do:** keep them; if the dashes bother, turn them into plain titles (`# Zones`).

## The "provisional" visual identity

`dashboard/src/styles.css:13` and `dashboard/src/app/ui/icon.ts:78`

```css
 * brand color, the same in both themes. Provisional: the final identity waits for the
 * commercial name (SPEC).
```

The name Willay was chosen on October 1, 2026, but SPEC still leaves the commercial name to validation after the MVP and to a trademark check with INDECOPI. Whether the colours and the eye logo are still provisional is a product decision.

**What I would do:** keep the comments until VIG-45 (public release) decides whether Willay's identity is final.
