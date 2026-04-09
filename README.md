# Just-in-Time (JIT) IAM System

A dynamic cloud Just-in-Time Identity and Access Management system designed to temporarily grant right-sized privileges to developers over shifting resources (VMs, Containers) on-demand through a Slack approval workflow.

## Motivation
In dynamic environments, creating long-lived credentials for resources is a security hazard. This JIT IAM system solves this by introducing auto-expiring access tokens tied exclusively to individual temporary resources, granted only upon request and valid approval, embodying the principle of least privilege.

## Features
- **Dynamic Resource Registration:** Cloud resources ping the IAM system on boot, keeping track of only active nodes.
- **On-Demand Access Requests:** Developers request time-bound scoped tokens.
- **Slack App Integration:** Auto-routes requests to a designated Slack channel for human 1-click approvals.
- **Auto-Expiring Cryptographic Tokens:** Tokens expire natively without needing backend cleanups (leveraging Redis TTL).
- **Stateless Validation:** Cloud resources can independently query `POST /validate` to ensure tokens are authorized securely.

## Quickstart (Hackathon Demo)

### 1. Prerequisites
- Docker & Docker Compose
- Target Python 3.11+
- (Optional but recommended) A Slack Bot Token + Signing secret

### 2. Running Locally using Docker
Spin up the backend API and the backing Redis instance cleanly to avoid setting up anything manual:
```bash
docker-compose up -d --build
```
This serves the API on `http://localhost:8000`.

### 3. Demo Test using the CLI `client.py`
We provide a simple CLI for interacting with the backend.

```bash
# Register a dummy resource representing a booted VM
python client.py register test-vm-1 vm

# Request access as a developer
python client.py request alice test-vm-1 "Investigating high latency"
```
Keep the generated `request_id`! To approve, since you might not have Slack set up during local dev without NGROK, you can check the status:
```bash
python client.py status <request_id>
```

### Testing
We provide an automated pytest suite. Needs a local Redis running on `:6379`.
```bash
pip install -r requirements.txt
pytest test_main.py -v
```
