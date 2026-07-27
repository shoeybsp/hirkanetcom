# SecureTrack‑Lite

A lightweight, open, extensible **firewall policy analysis engine** inspired by Tufin SecureTrack — built for **FortiGate**.  
It evaluates access requests using **CIDR‑aware logic**, ranks policies by **least‑privilege fit**, and provides a **clean Web UI**.

---

## ✨ Features

- Evaluate access requests using real **IP addresses**, **CIDRs**, or **service names**
- Full **policy ranking** with a least‑privilege scoring model
- Highlights the **best candidate policy**
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

## 🚀 Installation

### 1. Clone repository

```bash
git clone https://github.com/your-org/securetrack-lite.git
cd securetrack-lite
```

### 2. Install Python environment

Create and activate a venv:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Collect data from FortiGate

Create a FortiGate REST API admin/token, then run the collector. It uses FortiOS 6.4.x CMDB endpoints and does not require Ansible.

Using environment variables:

```bash
export FORTIGATE_HOST=192.168.1.99
export FORTIGATE_TOKEN='your-api-token'
export FORTIGATE_VDOM=root
python collectors/fortigate_collector.py
```

This populates:

```
data/policies.json
data/addresses.json
data/services.json
data/routes.json
data/interfaces.json
```

You can also pass options directly:

```bash
python collectors/fortigate_collector.py \
  --host 192.168.1.99 \
  --token 'your-api-token' \
  --vdom root
```

TLS verification is disabled by default because many FortiGate management interfaces use self-signed certificates. Add `--verify` when the certificate is trusted by your system.

`routes.json` is built from configured static routes plus the runtime IPv4 routing table at `/api/v2/monitor/router/ipv4`, so learned routes such as OSPF can be used for interface detection. If your REST API admin cannot access the monitor endpoint, the collector warns and still writes the static routes. Use `--skip-monitor-routes` to collect only static routes.

### 4. Start the Web UI

From project root:

```bash
python api/app.py
```

Open in browser:

```
http://127.0.0.1:5000
```

---

## 🐳 Docker

Build and run the web app with Docker:

```bash
docker build -t securetrack-lite .
docker run --rm -p 5000:5000 securetrack-lite
```

Open:

```
http://127.0.0.1:5000
```

For local development with your host `data/` directory mounted into the container:

```bash
docker compose up --build
```

The Compose setup mounts `./data` at `/app/data`, so changes from your FortiGate collection output are picked up the next time the container starts.

The container runs the Flask app with Gunicorn on port `5000` and includes a `/healthz` endpoint for Docker health checks.

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
- A complete **scored ranking** of all FortiGate policies
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

| Condition                              | Score |
|----------------------------------------|-------|
| Per matching source subnet             | +40   |
| Per matching destination subnet        | +40   |
| Per matching service                   | +20   |
| `all` usage                            | −15   |
| Each extra source/destination object   | −2    |
| Each extra service object              | −1    |

The best policy is the one with the **highest score**.

---

## 🔍 CIDR Matching Logic

Implemented via Python's `ipaddress`:

- Any user‑provided IP is converted to a `/32`
- Containment tested using `.subnet_of()`
- Address ranges, subnets, and host objects are normalized

---

## 🔁 Interface Auto‑Detection

The engine reads `routes.json` and picks:

- Longest-prefix match route
- Corresponding outgoing interface

When `routes.json` includes monitor routes, static and learned routes are considered together.

This helps validate whether the traffic path even matches the policy.

---

## 🏗️ Extending the Engine

The code is modular:

- Add new scoring rules
- Add shadow/overlap detection
- Integrate more FortiGate objects
- Add simulated policy-change output
- Add risk scoring

---

## 🛠️ Troubleshooting

### Engine shows "0 policies"

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

## 📄 License

<!-- Add your license information here -->