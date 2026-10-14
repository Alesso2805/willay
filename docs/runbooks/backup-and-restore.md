# Back up and restore the database

Willay keeps everything in one Postgres server, in two databases. Back up both: they refer to each other.

- **`willay`**: organizations, zones, stations, rules, incidents and their timelines, alerts, contacts, the audit log and the readings (a TimescaleDB hypertable).
- **`keycloak`**: users, their passwords, organizations and roles. Willay's users and organizations point to Keycloak's ids, so a `willay` database without its `keycloak` lets nobody sign in.

Neither dump contains the database roles or their passwords. Those come from `.env`, which the init script uses on an empty volume (ADR-0005), so keep a copy of `.env` somewhere safe as well. Never keep it next to the dumps in a public place: it holds every credential.

The commands below run from the repository's root, in any shell (PowerShell included). On a server, the `COMPOSE_FILE` that `make secrets` wrote into `.env` makes `docker compose` use the production overlay too. Each command was tested on a throwaway stack: the restored databases matched the originals, down to grants, the hypertable's compression and retention policies, and Keycloak's users.

## Back up

The stack can keep running: `pg_dump` reads a consistent snapshot.

```bash
docker compose exec postgres pg_dump -U postgres -Fc -f /tmp/willay.dump willay
docker compose exec postgres pg_dump -U postgres -Fc -f /tmp/keycloak.dump keycloak
docker compose cp postgres:/tmp/willay.dump ./willay.dump
docker compose cp postgres:/tmp/keycloak.dump ./keycloak.dump
docker compose exec postgres rm /tmp/willay.dump /tmp/keycloak.dump
```

`pg_dump` warns about "circular foreign-key constraints" on `continuous_agg`, a TimescaleDB catalog table. It is expected and harmless for a full dump restored as below.

Then move the two files off the machine (for example `scp` from the server): a backup on the same disk is lost with it. Name them by date, and keep several.

Why not `pg_dump ... > willay.dump`: Windows PowerShell 5.1 writes redirected output as UTF-16 text, which corrupts a binary dump. Writing the file inside the container and copying it out works in every shell.

## Restore

This replaces both databases with the backup. Everything written after the backup is lost.

### 1. Stop everything but Postgres

```bash
docker compose stop
docker compose up -d postgres --wait
```

### 2. Recreate both databases, empty, as the init script does

```bash
docker compose exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS willay WITH (FORCE)" -c "DROP DATABASE IF EXISTS keycloak WITH (FORCE)"
docker compose exec postgres psql -v ON_ERROR_STOP=1 -U postgres -c "CREATE DATABASE willay OWNER willay_owner" -c "REVOKE ALL ON DATABASE willay FROM PUBLIC" -c "GRANT CONNECT ON DATABASE willay TO willay_app" -c "CREATE DATABASE keycloak OWNER keycloak" -c "REVOKE ALL ON DATABASE keycloak FROM PUBLIC"
docker compose exec postgres psql -v ON_ERROR_STOP=1 -U postgres -d willay -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()"
```

A dump does not carry the database itself: its owner and who may connect to it. These lines set them as `infra/postgres/init/01-init.sh` does. `timescaledb_pre_restore()` tells TimescaleDB that a restore is coming, so its background jobs and catalog checks wait.

### 3. Restore the dumps

```bash
docker compose cp ./willay.dump postgres:/tmp/willay.dump
docker compose cp ./keycloak.dump postgres:/tmp/keycloak.dump
docker compose exec postgres pg_restore -U postgres -d willay /tmp/willay.dump
docker compose exec postgres psql -U postgres -d willay -c "SELECT timescaledb_post_restore()"
docker compose exec postgres pg_restore -U postgres -d keycloak /tmp/keycloak.dump
docker compose exec -u root postgres rm /tmp/willay.dump /tmp/keycloak.dump
```

`pg_restore` should finish without errors. The files copied in belong to root, hence `-u root` to delete them.

Restore into the same TimescaleDB version the backup came from: the image tag in `docker-compose.yml` pins it. If the code has moved on since the backup, the next step applies the missing migrations.

### 4. Start again

```bash
make up
```

`migrate` runs first: it finds the schema at the backup's version and applies whatever came after.

### 5. Verify

```bash
docker compose exec postgres psql -U postgres -d willay -c "SELECT version_num FROM alembic_version" -c "SELECT count(*) FROM ingest.readings" -c "SELECT count(*) FROM core.incidents"
```

Sign in to the dashboard, check that stations report again and that the incidents you expect are there.

## On a new server

If the whole server is gone, set up the new one with `docs/runbooks/deploy.md` up to `make secrets` (or restore the saved `.env`), then start only Postgres. On an empty volume the init script creates the roles and empty databases. Then follow the restore from step 2, which drops and recreates those databases, and do not run `make seed`.
