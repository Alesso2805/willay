# ADR-0004: Keycloak 26 Organizations como fuente de tenant y roles

- **Estado:** Propuesto (borrador de Sprint 0). Formato del claim verificado con Keycloak 26.7.4.
- **Fecha:** 2026-09-26
- **Relacionado:** SPEC.md › Arquitectura (Tenant y roles); VIG-02, VIG-06, VIG-07; `infra/keycloak/realm-vigia.json`

## Contexto

Vigía es multi-tenant: una municipalidad no debe ver jamás datos de otra, ni por REST ni por SSE. Keycloak 26 trae Organizations, pero sus **realm roles son globales**: un usuario con el rol `admin` lo tiene en todas sus organizaciones. Keycloak no tiene roles por organización sin extensiones.

## Opciones

1. **Roles y membresías en la base de Vigía**, con Keycloak solo para autenticar. Duplica la fuente de verdad.
2. **Grupos de Keycloak por organización** con roles en cada grupo. Funciona, pero no aprovecha Organizations.
3. **Keycloak Organizations y realm roles**, con la regla "un usuario pertenece a una sola organización".

## Decisión

Opción 3.

- **Una organización por usuario.** La API exige exactamente una organización en el token. Con cero o con varias responde **403**. Así los realm roles globales aplican sin ambigüedad a esa única organización.
- **Keycloak es la única fuente de roles:** `admin`, `operator`, `responder` y `viewer`, leídos de `realm_access.roles`. `core.users` no tiene columna de rol.
- **El tenant se resuelve solo por el id de la organización**, nunca por el alias (renombrable) ni por el nombre. `core.organizations.keycloak_org_id` es único.

### Formato del claim (verificado con tokens reales)

El mapper `oidc-organization-membership-mapper` del client scope `organization` se configura con **`addOrganizationId: true`**. Con esa opción, Keycloak 26.7.4 emite el claim como un **objeto indexado por alias**, no como una lista:

```json
"organization": { "rimac": { "id": "1d44f4b3-b1df-457f-b717-20926a20166e" } }
```

| Usuario de prueba | Claim `organization` | Respuesta de la API |
| --- | --- | --- |
| `rimac-operator` | `{"rimac": {"id": "1d44…"}}` | se resuelve el tenant por `id` |
| `dos-orgs` | `{"aislamiento": {...}, "rimac": {...}}` | 403 (varias) |
| `sin-org` | ausente | 403 (ninguna) |

La API valida que el claim sea un objeto con **exactamente una clave** y toma su `id`.

### Scope `organization:*`

Los clientes piden el scope **`organization:*`**, no `organization`. Con `organization` a secas, Keycloak pide al usuario elegir una organización si tiene varias (en el navegador) o no emite ninguna (password grant). Un usuario con varias organizaciones podría entonces elegir una y pasar la validación, llevando sus roles globales a esa organización. Con `organization:*` el token contiene todas las membresías y la regla de "exactamente una" se cumple de verdad.

### Configuración del realm

- `organizationsEnabled: true`. Organizaciones y usuarios con **ids fijos**: Keycloak los respeta al importar, y el seed usa los mismos ids.
- Declarar cualquier `clientScopes` en el JSON desactiva la creación de los scopes por defecto. Por eso el realm incluye los 15 scopes exportados de Keycloak 26.7.4, con el único cambio de `addOrganizationId` en el mapper de `organization`. Sin `basic` y `roles` los tokens no traían `sub` ni `realm_access`.
- **Clientes:**
  - `vigia-dashboard`: público, Authorization Code con PKCE S256;
  - `vigia-api`: solo audiencia (`bearerOnly`);
  - `vigia-dev-cli`: público con password grant, **solo desarrollo**, para curl y tests.
  - Los dos primeros incluyen la audiencia `vigia-api`.
- Las contraseñas de los usuarios de prueba son el placeholder `${VIGIA_DEV_USER_PASSWORD}`, sustituido desde el entorno al importar.

## Consecuencias

- **A favor:** una sola fuente de identidad, organización y roles. El aislamiento se aplica en una dependencia obligatoria de FastAPI que toda consulta y el canal SSE usan.
- **En contra:** soportar varias organizaciones por usuario (por ejemplo, un consultor que atiende a dos municipalidades) exigirá roles por organización: atributos de membresía o grupos. Queda fuera del MVP.
- **En contra:** el formato del claim depende de una opción del mapper. Si Keycloak lo cambia en otra versión, los tests de VIG-06 con los usuarios `rimac-operator`, `sin-org` y `dos-orgs` lo detectarán.
- **Seguridad:** `vigia-dev-cli` con password grant no debe existir fuera de desarrollo. El realm de producción se generará sin ese cliente.
