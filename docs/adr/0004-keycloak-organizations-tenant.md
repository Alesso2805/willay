# ADR-0004: Keycloak 26 Organizations as the source of tenant and roles

- **Status:** Accepted on 2026-10-13. Claim format verified with Keycloak 26.7.4.
- **Date:** 2026-09-26
- **Related:** SPEC.md › Architecture (Tenant and roles); VIG-02, VIG-06, VIG-07; `infra/keycloak/realm-willay.json`

## Context

Willay is multi-tenant: one municipality must never see another's data, neither through REST nor through SSE. Keycloak 26 ships Organizations, but its **realm roles are global**: a user with the `admin` role has it in all of their organizations. Keycloak has no per-organization roles without extensions.

## Options

1. **Roles and memberships in Willay's database**, with Keycloak only for authentication. It duplicates the source of truth.
2. **Keycloak groups per organization** with roles on each group. It works, but does not take advantage of Organizations.
3. **Keycloak Organizations and realm roles**, with the rule "a user belongs to a single organization".

## Decision

Option 3.

- **One organization per user.** The API requires exactly one organization in the token. With zero or with several it answers **403**. That way the global realm roles apply unambiguously to that single organization.
- **Keycloak is the only source of roles:** `admin`, `operator`, `responder` and `viewer`, read from `realm_access.roles`. `core.users` has no role column.
- **The tenant is resolved only by the organization id**, never by the alias (which can be renamed) or by the name. `core.organizations.keycloak_org_id` is unique.

### Claim format (verified with real tokens)

The `oidc-organization-membership-mapper` mapper of the `organization` client scope is configured with **`addOrganizationId: true`**. With that option, Keycloak 26.7.4 emits the claim as an **object keyed by alias**, not as a list:

```json
"organization": { "rimac": { "id": "1d44f4b3-b1df-457f-b717-20926a20166e" } }
```

| Test user | `organization` claim | API response |
| --- | --- | --- |
| `rimac-operator` | `{"rimac": {"id": "1d44…"}}` | the tenant is resolved by `id` |
| `dos-orgs` | `{"aislamiento": {...}, "rimac": {...}}` | 403 (several) |
| `sin-org` | absent | 403 (none) |

The API checks that the claim is an object with **exactly one key** and takes its `id`.

### `organization:*` scope

Clients request the **`organization:*`** scope, not `organization`. With plain `organization`, Keycloak asks the user to pick an organization if they have several (in the browser) or emits none (password grant). A user with several organizations could then pick one and pass validation, carrying their global roles into that organization. With `organization:*` the token contains every membership, and the "exactly one" rule is genuinely enforced.

### Realm configuration

- `organizationsEnabled: true`. Organizations and users with **fixed ids**: Keycloak keeps them on import, and the seed uses the same ids.
- Declaring any `clientScopes` in the JSON disables the creation of the default scopes. That is why the realm includes the 15 scopes exported from Keycloak 26.7.4, with `addOrganizationId` in the `organization` mapper as the only change. Without `basic` and `roles`, tokens came without `sub` or `realm_access`.
- **Clients:**
  - `willay-dashboard`: public, Authorization Code with PKCE S256;
  - `willay-api`: audience only (`bearerOnly`);
  - `willay-dev-cli`: public with password grant, **development only**, for curl and tests.
  - The first two include the `willay-api` audience.
- The passwords of the test users are the `${WILLAY_DEV_USER_PASSWORD}` placeholder, substituted from the environment on import.

## Consequences

- **Pro:** a single source of identity, organization and roles. Isolation is enforced in a mandatory FastAPI dependency that every query and the SSE channel use.
- **Con:** supporting several organizations per user (for example, a consultant who serves two municipalities) will require per-organization roles: membership attributes or groups. Out of scope for the MVP.
- **Con:** the claim format depends on a mapper option. If Keycloak changes it in another version, the VIG-06 tests with the users `rimac-operator`, `sin-org` and `dos-orgs` will catch it.
- **Security:** `willay-dev-cli` with password grant must not exist outside development. The production realm will be generated without that client.
