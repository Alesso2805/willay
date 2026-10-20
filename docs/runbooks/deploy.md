# Deploy Willay on a server

This runbook puts Willay on a public server, with HTTPS, so anyone with the link can use it (VIG-42). It targets an **Oracle Cloud Always Free** ARM server and a free **DuckDNS** hostname, so it costs nothing. The same steps work on any Linux server with Docker, on x86 or ARM, as long as a hostname points to it; [Google Cloud's free trial](#on-google-cloud-instead) is the alternative the public demo runs on.

One hostname serves everything, behind Caddy (ADR-0010):

| Path | What |
| --- | --- |
| `/` | the dashboard |
| `/api` | the API, and the confirmation links in the emails |
| `/auth` | Keycloak's sign-in (its admin console is not public: see [Administer Keycloak](#administer-keycloak)) |
| `/correo` | Mailpit: the emails Willay sends, caught before they reach anyone |

## 1. The Oracle Cloud account

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com). A card is asked for to verify identity; Always Free resources are not charged.
2. **Pick the home region carefully: it cannot be changed later.** Pick one close to your users that has Ampere (ARM) capacity, such as Santiago or São Paulo for South America.
3. Recommended: upgrade the account to **Pay As You Go** (Billing → Upgrade).
   - You still pay nothing while you stay within the Always Free limits.
   - Oracle may reclaim an idle Always Free server only on free-tier accounts.
   - Add a budget alert of US$1 (Billing → Budgets) to hear about any charge right away.

## 2. The server

1. **Compute → Instances → Create instance:**
   - **Image:** Canonical Ubuntu 24.04 (aarch64).
   - **Shape:** `VM.Standard.A1.Flex` with 2 OCPUs and 12 GB of memory. Always Free allows up to 4 OCPUs and 24 GB in total. Willay needs about 2 GB of memory and 10 GB of disk.
   - **Networking:** create a new virtual cloud network with a public subnet, and assign a public IPv4 address.
   - **SSH keys:** upload your public key (`~/.ssh/id_ed25519.pub`), or let Oracle generate a pair and download it.
   - **Boot volume:** 50 GB (Always Free covers up to 200 GB).

   If it answers "Out of capacity", try another availability domain or try again later; ARM capacity comes and goes.
2. **Open ports 80 and 443 to the internet,** in two places:
   - **In the network:** Networking → Virtual cloud networks → your network → its subnet → its security list → Add ingress rules. Add source `0.0.0.0/0`, TCP, destination ports `80,443`, and a second rule for UDP `443` (HTTP/3).
   - **On the server:** Oracle's Ubuntu image ships a firewall that only lets SSH in. Over SSH (`ssh ubuntu@<public IP>`):

     ```bash
     sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
     sudo iptables -I INPUT -p udp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```

### On Google Cloud instead

Google Cloud's free trial gives $300 of credit for 90 days and charges nothing while it lasts. When the credit or the 90 days run out, the server stops; nothing is charged unless you upgrade the account yourself. The public demo runs this way since October 2026.

1. **Start the free trial** at [console.cloud.google.com/freetrial](https://console.cloud.google.com/freetrial).
   - The billing account must say **Cuenta de prueba gratuita** (free trial account). A paid account would charge the server to the card.
   - With some cards, Google asks for a one-time prepayment (PEN 100 in Peru). It stays as account balance and is refundable when the billing account is closed. Until it is credited, the trial is not active and the account cannot be linked to a project.
   - Never press **Upgrade** (*Actualizar*) on the trial banner: that turns the account into a paid one.
2. **A project** named `willay`, linked to the trial billing account.
3. **Compute Engine → VM instances → Create instance:**
   - **Region:** `southamerica-west1` (Santiago), the closest to Peru.
   - **Machine:** E2, `e2-medium` (2 vCPU, 4 GB), about US$40 a month of credit.
   - **OS and storage:** Ubuntu 24.04 LTS for x86/64 (not *Minimal*, which lacks tools the next steps use), 30 GB.
   - **Networking:** allow HTTP and HTTPS traffic, which opens ports 80 and 443. In the network interface, reserve a **static external IPv4 address**, so the IP survives a restart.
   - **Observability:** leave the Ops Agent off: Willay does not need it, and it takes memory.
4. **Connect** with the **SSH** button next to the instance, which opens a terminal in the browser. Ubuntu on Google Cloud has no firewall of its own to open, so go on to DuckDNS with the instance's external IP.

## 3. A free hostname with DuckDNS

1. Sign in at [duckdns.org](https://www.duckdns.org) with GitHub or Google.
2. Add a subdomain, for example `willay`, which gives you `willay.duckdns.org`.
3. Set its IP to the server's public IP and press **update ip**.

The public IP stays with the server for as long as it exists. If you ever recreate the server, update the IP in DuckDNS. Caddy needs the hostname to resolve before it can get the certificate.

## 4. Docker and the repository

On the server:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
sudo apt-get install -y make git
exit    # log in again so the docker group applies
```

Then clone the repository:

```bash
git clone https://github.com/Alesso2805/willay.git
cd willay
```

While the repository is private, the clone asks for credentials. Use `gh auth login`, or a fine-grained token with read access to its contents as the password.

## 5. Start it

```bash
make secrets HOST=willay.duckdns.org DEMO=1   # .env with new credentials, only on this server
make up                                       # builds and starts everything; Caddy gets the certificate
make seed                                     # the demo data
```

- The first `make up` builds the images on the server, which takes about 10 minutes on ARM, and waits until every service reports healthy.
- Open `https://willay.duckdns.org`.
- `.env` and `.secrets/station-keys.json` hold this server's credentials. They never leave it, and they are not in the repository.

`make secrets` also sets `COMPOSE_FILE` in `.env`, so every `docker compose` and `make` command on the server uses `docker-compose.prod.yml` on top of `docker-compose.yml`.

### The public demo (`DEMO=1`)

`DEMO=1` turns on the public demo (VIG-43). It sets `WILLAY_DEMO_MODE=true`, `WILLAY_DEMO_PASSWORD=willay-demo` and `COMPOSE_PROFILES=demo` in `.env`; the last one starts the `worker-demo` service. What a visitor gets:

- **Demo accounts on the sign-in screen,** with the shared password and four steps to try:
  - `demo-admin` sees and manages everything, and runs the scenario;
  - `demo-operator` manages zones, stations, rules and incidents;
  - `demo-viewer` only looks.
- **No way to change that password.** Caddy closes Keycloak's account console and its API, every path under `/account`; the dashboard never uses them.
- **Live stations.** The demo worker keeps every Rímac station reporting every 10 s, so the map is live from the first visit.
- **The scenario button.** "Correr el escenario" on Inicio plays SPEC's Rímac story in 9 minutes, one run at a time, with its progress on screen. Every run starts from a clean slate.
- **The emails** Willay sends, readable at `/correo` (Mailpit). Nothing leaves the server.
- **A nightly restore** at 04:00 in the organization's time zone: the demo organization goes back to the seed. What visitors changed during the day disappears: zones, rules, contacts, incidents, the audit log, their language.

The private accounts (`rimac-admin`, `rimac-operator`, `rimac-responder` and `rimac-viewer`) keep the random password `WILLAY_DEV_USER_PASSWORD` that `make secrets` wrote into `.env` (`grep WILLAY_DEV_USER_PASSWORD .env`). Without `DEMO=1`, they are the only accounts.

The demo accounts exist in Keycloak's realm file, so they are created on Keycloak's first start. To turn the demo on later on a running server, add the three demo lines to `.env` and run `make up`. Keycloak, however, keeps the demo accounts' password from its first start: the development one if the demo was off then.

### Check it from your machine

From the repository on your own machine, not on the server. These checks run in Node 20+ and need no browser:

```bash
cd e2e && npm ci
WILLAY_E2E_DEPLOYED=1 WILLAY_DASHBOARD_URL=https://willay.duckdns.org npx playwright test deployed.spec.ts
```

They check that the dashboard, the API, the sign-in and the mailbox answer on the one hostname, that the sign-in page shows the Willay icon, and that `config.json` holds the demo's shared password and nothing else. They also check that Keycloak's admin console, its master realm and the account console answer 404 from the internet. In PowerShell, set the two variables with `$env:WILLAY_E2E_DEPLOYED=1` and `$env:WILLAY_DASHBOARD_URL="https://..."` first.

## 6. Update

```bash
cd willay
git pull
make up
```

The `migrate` container applies any new migration before the API and the workers start.

A change to the realm file does not reach a running server on its own (see [Administer Keycloak](#administer-keycloak)). One did: since October 2026 the sign-in page uses Willay's login theme, which shows its icon in the browser tab. On a server started before that, set it once after `make up`:

```bash
docker compose exec keycloak bash -c '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080/auth --realm master --user admin --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" && /opt/keycloak/bin/kcadm.sh update realms/willay -s loginTheme=willay'
```

## Administer Keycloak

The admin console is never reachable through the public hostname: Caddy answers 404 for `/auth/admin` and for the `master` realm. Keycloak listens only on the server's loopback, at `127.0.0.1:8081`. To reach it, open an SSH tunnel from your machine:

```bash
ssh -L 8081:127.0.0.1:8081 ubuntu@<public IP>
```

Then open `http://localhost:8081/auth/admin`. The user is `admin` and the password is `KEYCLOAK_ADMIN_PASSWORD` in the server's `.env`.

The realm's configuration (clients, users, organizations) comes from `infra/keycloak/realm-willay.json` and is applied only on Keycloak's first start, with an empty database. Later changes to the file need either the console or a fresh Keycloak database.

## Troubleshooting

| Symptom | Look at |
| --- | --- |
| The browser cannot connect | Ports 80 and 443 in the security list and in `iptables`; whether the DuckDNS hostname resolves to the server (`nslookup willay.duckdns.org`) |
| The certificate is not issued | `docker compose logs caddy`. Let's Encrypt must reach the server on port 80 under that hostname |
| Sign-in fails or loops | `docker compose logs keycloak api`. `WILLAY_HOSTNAME` in `.env` must be the hostname in the browser's address bar |
| "Acceso no permitido" after signing in | `make seed` was not run: the organizations do not exist yet |
| A service is not healthy | `docker compose ps` and `docker compose logs <service>` |
