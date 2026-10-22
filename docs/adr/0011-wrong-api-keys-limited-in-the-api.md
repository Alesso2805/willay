# ADR-0011: Wrong API keys limited per address, in the API

- **Status:** Accepted on 2026-10-22
- **Date:** 2026-10-22
- **Related:** SPEC.md › Architecture (Rate limit) and › Backlog › VIG-47; ADR-0002; ADR-0010

## Context

A station authenticates each batch with an API key whose hash is Argon2id: 50 to 130 ms of CPU on purpose, so a stolen hash cannot be brute-forced. The API remembers a key it verified, so a station pays that cost once per process. A wrong key, or a key for a station that does not exist, pays it every time.

Until now nothing limited those requests. The per-station limit (60 batches a minute) is counted after authenticating, because it needs to know the station. A comment said the proxy limited wrong keys by IP, and nothing did. Anyone could make the API run Argon2id as fast as they could send requests, and fill the threads that verify keys for real stations.

Many stations reach the internet through a mobile carrier's NAT, so several of them can share one public address.

## Options

1. **In Caddy** (ADR-0010). The standard Caddy has no rate limiting; it needs a third-party module and a custom build of the image. Caddy cannot tell a wrong key from a right one either, so it would limit every request from the address, valid stations included.
2. **In the API, in memory.** It is simple, but each replica would count on its own, and the count would reset on every restart.
3. **In the API, in Postgres,** like the per-station limit (ADR-0002): one counter per client address and minute, updated with an atomic upsert.

## Decision

Option 3, in `current_station`, before the key is verified:

- **What counts:** only a check that must run Argon2id. A key the process already verified is answered from memory, costs nothing and is not counted, so a valid station never uses up its address's allowance. A malformed key never reaches Argon2id and is not counted either.
- **When it counts:** before the check runs, so a concurrent burst runs no more checks than the limit. A key that turns out right, including one for an inactive station, takes its count back.
- **The limit:** 30 a minute per client address (`MAX_KEY_FAILURES_PER_MINUTE`). A misconfigured station retrying every 5 s fails 12 times a minute, so it does not lock out the stations that share its address.
- **Over the limit:** 429 with `Retry-After` until the next minute, and the code `key_failures_limited`.
- **The address:** Caddy sends it in `X-Forwarded-For`, and uvicorn's `--proxy-headers` makes it the request's client. In production the API has no published port, so only Caddy reaches it.
- **Storage:** `ingest.key_failure_windows`, purged by the silence worker with the per-station windows, after an hour.

## Consequences

- **Pro:**
  - A client sending wrong keys gets at most 30 Argon2id checks a minute from each address.
  - The count holds with several API replicas and across restarts.
  - Valid stations write nothing more: their keys are remembered.
- **Con:**
  - Up to twice the limit fits around a minute boundary, as with the per-station limit.
  - While an address is over its limit, a key from it that this process has not verified yet waits too, until the next minute. Right after the API restarts, more than 30 stations behind one address that send at the same moment can get a 429 once, and are verified when they retry.
  - Someone with many addresses gets 30 checks a minute from each. Stopping that takes a limit across addresses, and the evidence of an attack to justify it.
