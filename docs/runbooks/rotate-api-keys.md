# Rotate a station's API key

Each station authenticates its batches with its own API key (`X-Api-Key: <station_id>.<secret>`). Willay keeps only an Argon2id hash of it, so a lost key cannot be recovered: it is replaced. Rotate a key when:

- it may have leaked (a log, a chat, a screenshot, a lost or stolen datalogger);
- the device that holds it is replaced, or someone who knew it leaves;
- as routine, if your organization rotates credentials periodically.

## What happens when you rotate

- **The old key stops working at once**, on every API replica. Each request reads the station's current hash from the database. The memory of verified keys that each API process keeps (VIG-29) is tied to that hash, so it cannot keep the old key alive.
- **The new key is shown once.** Willay only stores its hash.
- **Until the station is reconfigured, its batches get 401.** If it sits in a zone with a silence rule, a silence incident opens after K × its expected interval and alerts go out as for any silent station. Either reconfigure the device straight away, or warn the people on the escalation policy first.

## 1. Rotate it from the dashboard

Sign in as an operator or admin. In **Estaciones** (Stations), find the station and press **Rotar clave** (Rotate key). Confirm: the dialog reminds you that the current key stops working at once.

A notice shows the new key: **"API key de \<code\>"**. Copy it with **Copiar** (Copy) and press **Ya la guardé** (I have saved it) only when it is safe somewhere. After that, it is not shown again.

## 2. Configure the station

Put the new key in the station's datalogger or gateway, as the value of the `X-Api-Key` header of its `POST /v1/readings` requests. The key carries the station's id before the dot, so it cannot be used for another station.

## 3. Verify

- **The station reports again.** In **Estaciones** or **Mapa en vivo** it shows as reporting, with a fresh last value, within one expected interval.
- **The old key is refused.** A request with it gets 401.
- **The audit log has it.** Admins see "Rotó la API key de la estación \<code\>" in **Auditoría**, with who did it and when.

If a silence incident opened meanwhile, the silence worker records `station_recovered` when the station reports again; resolve the incident (it is not closed automatically).

## Without the dashboard

The dashboard calls `POST /v1/stations/{station_id}/api-key` with the user's token: an operator's or an admin's. The response carries the new key once, in `api_key`, and is marked `Cache-Control: no-store`.

## On a development machine

`make seed` saves the seed stations' keys in `.secrets/station-keys.json`, which `make simulate` and `make demo` read. `make seed ARGS=--rotate-keys` rotates all of them and rewrites the file. A station rotated from the dashboard needs its `api_key` updated in that file by hand.
