
# SecureTrack‑Lite  
A lightweight, open, extensible **firewall policy analysis engine** inspired by Tufin SecureTrack — built for **FortiGate**.  
It evaluates access requests using **CIDR-aware logic**, ranks policies by **least-privilege fit**, and provides a **clean Web UI**. The evaluator is a decision-support service: its results are heuristic recommendations, not authoritative FortiGate packet-flow simulation results.

---


## Evaluation scope and limitations

The Secure Track FortiGate Policy Evaluator is a **heuristic candidate-ranking engine**. It compares a requested source, destination, and service with collected FortiGate objects, routes, interfaces, and enabled accept policies. Its score is intended to help an engineer identify policies that may already cover a request or may be reasonable least-privilege extension candidates.

It does **not** reproduce FortiGate's complete runtime packet-processing pipeline and must not be treated as proof that traffic is allowed, denied, routed, translated, or reachable. In particular, the current engine does not fully model policy order, explicit deny interactions, schedules, NAT and central SNAT, identity-based policy, zones, internet-service objects, dynamic objects, policy routes, session state, multi-VDOM behavior, or downstream network reachability.

Every recommendation must therefore be reviewed against the complete FortiGate configuration and validated through the organization's normal change-control, testing, and rollback procedures.

---

## ✨ Features

- Evaluate access requests using real **IP addresses**, **CIDRs**, or **service names**
- Full **policy ranking** with a least‑privilege scoring model
- Highlights the **top recommended policy candidate**
- CIDR-aware matching using Python's `ipaddress`
- Auto interface detection using FortiGate routing tables
- Modern web UI (Flask + Bootstrap)
- REST endpoint (`/evaluate`) for automation
- Extensible engine with modular structure
- Python requests collector for FortiGate 6.4.x:
  - Firewall policies  
  - Address objects  
  - Address groups
  - Service objects and groups
  - Routing table
  - Interfaces

---

## 📁 Project Structure

```
securetrack-lite/
│
├── api/                    # Flask Web Application (UI + REST API)
│   └── app.py
│
├── engine/                 # Core evaluation logic
│   ├── evaluator.py
│   ├── cidr_tools.py
│   └── interface_selector.py
│
├── templates/              # Web UI HTML templates
│   ├── index.html
│   └── results.html
│
├── static/                 # Stylesheets, JS, images
│   └── style.css
│
├── data/                   # JSON data pulled from FortiGate
│   ├── addresses.json
│   ├── policies.json
│   └── routes.json
│
├── collectors/             # Python REST collector
│   └── fortigate_collector.py
│
├── requirements.txt        # Python dependencies
└── README.md               # Documentation
```

---


### Secret files

Production credentials and encryption keys are supplied as Docker secrets, not ordinary Compose environment values. Copy `.env.example` to `.env` for non-secret settings, create the extensionless files listed in `secrets/README.md`, and restrict them to the deployment account.

## 🚀 Installation

### 1. Clone repository

```bash
git clone https://github.com/your-org/securetrack-lite.git
cd securetrack-lite
```

---

## 🐍 2. Install Python environment

Create and activate a venv:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 🔧 3. Collect data from FortiGate

Create a FortiGate REST API admin/token, then run the collector. It uses FortiOS
6.4.x CMDB endpoints and does not require Ansible.

Using environment variables:

```bash
export FORTIGATE_HOST=192.168.1.99
export FORTIGATE_TOKEN='your-api-token'
export FORTIGATE_VDOM=root
python collectors/fortigate_collector.py
```

This publishes an immutable snapshot under `data/snapshots/<snapshot-id>/` and atomically updates `data/current.json`. Each snapshot contains:

```
policies.json
addresses.json
services.json
routes.json
interfaces.json
manifest.json
```

See `FORTIGATE-SNAPSHOTS.md` for atomic publication, retention, verification, rollback, and backup procedures.

You can also pass options directly:

```bash
python collectors/fortigate_collector.py \
  --host 192.168.1.99 \
  --token 'your-api-token' \
  --vdom root
```

TLS verification is disabled by default because many FortiGate management
interfaces use self-signed certificates. Add `--verify` when the certificate is
trusted by your system.

`routes.json` is built from configured static routes plus the runtime IPv4
routing table at `/api/v2/monitor/router/ipv4`, so learned routes such as OSPF
can be used for interface detection. If your REST API admin cannot access the
monitor endpoint, the collector warns and still writes the static routes. Use
`--skip-monitor-routes` to collect only static routes.

---

## 🌐 4. Start the Web UI

From project root:

```bash
python api/app.py
```

Open in browser:

```
http://127.0.0.1:5000
```

---


## Split Docker Compose stacks

Hirkanet uses two independent Compose projects:

- `docker-compose.yml`: application and PostgreSQL
- `docker-compose.elastic.yml`: Elasticsearch, Logstash, Kibana, Filebeat, and Elastic bootstrap services

Start the application stack:

```bash
docker compose up -d --build
```

Start the observability stack separately:

```bash
docker compose -f docker-compose.elastic.yml up -d
```

The stacks do not share a Docker network. Filebeat discovers application and database logs from the Docker host using the `hirkanet_log_role` labels. See `COMPOSE-DEPLOYMENT.md` for operations and cleanup.

## 🐳 Docker

Build and run the web app with Docker:

```bash
docker build -t securetrack-lite .
docker run --rm -p 5000:5000 securetrack-lite
```

Open:

```text
http://127.0.0.1:5000
```

For local development with your host `data/` directory mounted into the container:

```bash
docker compose up --build
```

The Compose setup mounts `./data` at `/app/data`. The collector publishes immutable snapshots through `data/current.json`, and the running web application automatically reloads the evaluator when the active snapshot ID changes.

The container runs the Flask app with Gunicorn on port `5000`. Compose uses the database-backed `/readyz` endpoint for application readiness; `/livez` remains available as a process-level liveness endpoint.

Runtime health checks validate service behavior rather than only open ports:

- PostgreSQL executes an authenticated `SELECT 1`.
- Elasticsearch waits for a non-timed-out yellow or green cluster state over authenticated HTTPS.
- Logstash verifies that its `main` pipeline is loaded through the local node API.
- Kibana requires its status API to report `available`.
- Filebeat runs its native output test, including TLS connectivity to Logstash.
- Hirkanet calls `/readyz`, which also verifies database access.

The Compose deployment uses three isolated internal networks:

- `app-db` for Hirkanet and PostgreSQL
- `logging-ingest` for Filebeat and Logstash
- `elastic-backend` for Logstash, Elasticsearch, Kibana, and Elastic initialization

Logstash is the only service attached to both logging networks. The certificate setup container has networking disabled.

---

## 🖥️ Web UI Usage

Enter:

- Source IPs, subnets, or address object names
- Destination IPs, subnets, or address object names
- Services (FortiGate service names)

Example:

```
Sources: 192.168.10.25,192.168.0.0/24
Destinations: 10.10.10.15
Services: tcp-443,tcp-8443
```

The UI displays:

- The **best-matching policy**
- A complete **heuristic scored ranking** of FortiGate policy candidates
- Source, destination, and service match counts
- Interfaces (src → dst)
- Penalties for wide rules (like `all`)

---

## 🔌 REST API (Automation)

The engine exposes a JSON endpoint:

### POST /evaluate

**URL**

```
http://127.0.0.1:5000/evaluate
```

**Body**

```json
{
  "src": ["192.168.1.10"],
  "dst": ["10.10.10.50"],
  "services": ["tcp-443"]
}
```

**Response example**

```json
[
  {
    "policyid": 12,
    "name": "Allow-HTTPS",
    "score": 113,
    "src_matches": 1,
    "dst_matches": 1,
    "srv_matches": 1,
    "srcintf": ["port1"],
    "dstintf": ["port2"]
  }
]
```

---

## 🧠 How the Scoring Works

Policies are ranked with a **least‑privilege** scoring model:

Scoring highlights:

- +40  per matching source subnet
- +40  per matching destination subnet
- +20  per matching service
- −15 for `all` usage
- −2  for each extra source/destination address object
- −1  for each extra service object

The best policy is the one with **highest score**.

---

## 🔍 CIDR Matching Logic

Implemented via Python’s `ipaddress`:

- Any user‑provided IP is converted to a `/32`
- Containment tested using `.subnet_of()`
- Address ranges, subnets, and host objects are normalized

---

## 🔁 Interface Auto‑Detection

The engine reads `routes.json` and picks:

- Longest-prefix match route
- Corresponding outgoing interface

When `routes.json` includes monitor routes, static and learned routes are
considered together.

This helps validate whether the traffic path even matches the policy.

---

## 🏗️ Extending the Engine

The code is modular:

- Add new scoring rules
- Add shadow/overlap detection
- Integrate more FortiGate objects
- Add simulated policy-change output
- Add risk scoring



## Database migrations

Hirkanet uses **Flask-Migrate/Alembic**. Gunicorn startup never calls `db.create_all()` or changes the schema implicitly. The application Compose project runs a one-shot `migrate` service before `app`; it applies `flask db upgrade` and then performs idempotent default-data seeding.

```bash
docker compose up -d --build
docker compose logs migrate
```

The baseline migration safely adopts databases created by earlier Hirkanet versions. Back up PostgreSQL before the first migration-managed deployment. See [`DATABASE-MIGRATIONS.md`](DATABASE-MIGRATIONS.md) for revision creation, deployment, rollback, and existing-database adoption.

## 🛠️ Troubleshooting

### Engine shows “0 policies”
Check:

```
data/policies.json
data/addresses.json
data/routes.json
```

If empty → rerun collectors.

### Services do not match
Ensure service names match FortiGate names exactly (e.g., `HTTPS`, `tcp-443`, etc.)

---


### Application container hardening

The Compose application service runs with a read-only root filesystem, no Linux capabilities, and `no-new-privileges`. A small `noexec`, `nosuid`, and `nodev` temporary filesystem is mounted at `/tmp`. Only `/app/data`, `/app/uploads`, and `/app/static/uploads` are writable because they contain runtime FortiGate data and user-managed uploads. Gunicorn receives a 30-second graceful shutdown period.

### Container resource limits

The Compose deployment defines CPU, memory, memory-reservation, and PID limits for every service. Elasticsearch is limited to 1.5 CPUs and 1536 MB of memory with a 512 MB JVM heap; Logstash is limited to 1 CPU and 768 MB with a 256 MB JVM heap. These defaults target a small single-host deployment and should be capacity-tested before production use. Increase both the container memory limit and JVM heap deliberately; never raise the heap to the full container limit because Elastic services also require native memory and filesystem cache.

## Dead-letter retention

Malformed application JSON is isolated under the `hirkanet-dead-letter` rollover alias and deleted by ILM after 30 days.

---

## Public HTTPS deployment

Production access must use **`https://hirkanet.com`**. The `www.hirkanet.com` hostname is supported but redirects permanently to the canonical apex domain. The Gunicorn port remains bound to `127.0.0.1:5000` and must never be exposed directly to the internet.

A trusted reverse proxy must terminate TLS, redirect HTTP to HTTPS, set the standard `X-Forwarded-*` headers, and proxy to the loopback-bound application. The supplied Nginx configuration and complete DNS, certificate, firewall, HSTS, and verification instructions are in [`HTTPS-DEPLOYMENT.md`](HTTPS-DEPLOYMENT.md).

## Elastic certificate lifecycle

Elastic startup reuses its existing CA and refuses silent trust-root replacement. See `ELK-SETUP.md` and use `elk/rotate-elastic-ca.sh --confirm-trust-root-rotation` only for an intentional CA rotation.


## Identity storage

PostgreSQL is the sole source of truth for user identities, password hashes, roles, subscriptions, services, and blog metadata. Hirkanet does not use a JSON-backed user database.

## PostgreSQL backups

The PostgreSQL named volume provides persistence but is not a backup. Hirkanet
includes verified backup and restore tooling under `scripts/`. Create a backup
and automatically test it with:

```bash
./scripts/postgres-backup.sh
```

See `STORAGE-MONITORING.md` for capacity thresholds, backup freshness checks, alert exit codes, and safe retention enforcement.

See `POSTGRES-BACKUP-RESTORE.md` for retention, off-host storage, restore tests,
and the guarded production recovery procedure.

### Transaction safety

All application writes use a centralized transaction boundary. Failed integrity checks, connection errors, or flush/commit failures rollback the SQLAlchemy session before another query can reuse it. Default-data seeding is atomic, so a failed seed cannot leave a partially initialized database.
