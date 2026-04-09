import os
import json
import time
import secrets
import asyncio
from datetime import datetime
from typing import Optional

import fakeredis
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

REDIS_URL         = os.getenv("REDIS_URL", "redis://localhost:6379")
SLACK_BOT_TOKEN   = os.getenv("SLACK_BOT_TOKEN", "xoxb-dummy-1234")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "dummy-secret-1234")
APPROVAL_CHANNEL  = os.getenv("APPROVAL_CHANNEL", "#access-approvals")
CREDENTIAL_TTL    = int(os.getenv("CREDENTIAL_TTL", 3600))   # 1 hour default

# ─────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────

app = FastAPI(
    title="JIT IAM System",
    description="Just-in-Time IAM for dynamic cloud environments",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("frontend", exist_ok=True)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", summary="Serve Frontend UI")
async def serve_frontend():
    return FileResponse("frontend/index.html")

r = fakeredis.FakeStrictRedis(decode_responses=True)

slack_app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
slack_handler = AsyncSlackRequestHandler(slack_app)

# ─────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────

class AccessRequest(BaseModel):
    developer_id: str
    resource_id: str
    reason: str
    ttl: Optional[int] = CREDENTIAL_TTL       # seconds

class ResourceRegister(BaseModel):
    resource_id: str
    resource_type: str                          # container | vm | pod
    region: Optional[str] = "us-east-1"
    tags: Optional[dict] = {}

class ValidateRequest(BaseModel):
    token: str
    resource_id: str

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def save_request(request_id: str, data: dict, ttl: int = 86400):
    """Persist access request to Redis with 24h TTL."""
    r.setex(f"request:{request_id}", ttl, json.dumps(data))

def get_request(request_id: str) -> dict:
    raw = r.get(f"request:{request_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Request not found or expired")
    return json.loads(raw)

def issue_credential(request_id: str, resource_id: str,
                     developer_id: str, ttl: int) -> dict:
    """Generate scoped, time-limited credential and store in Redis."""
    token = secrets.token_urlsafe(32)
    credential = {
        "token":        token,
        "request_id":   request_id,
        "resource_id":  resource_id,
        "developer_id": developer_id,
        "permissions":  ["read", "exec"],       # least privilege
        "issued_at":    time.time(),
        "expires_at":   time.time() + ttl,
        "ttl_seconds":  ttl,
    }
    # Redis auto-deletes after TTL → automatic expiry, no cleanup needed
    r.setex(f"cred:{token}", ttl, json.dumps(credential))
    return credential

def validate_credential(token: str, resource_id: str) -> tuple[bool, dict | str]:
    """Validate token exists, is not expired, and is scoped to the resource."""
    raw = r.get(f"cred:{token}")
    if not raw:
        return False, "Token expired or invalid"
    cred = json.loads(raw)
    if cred["resource_id"] != resource_id:
        return False, "Token not scoped to this resource"
    return True, cred

def get_developer_slack_id(developer_id: str) -> str:
    """Lookup Slack user ID from developer_id stored in Redis."""
    return r.get(f"dev_slack:{developer_id}") or developer_id

def log_audit(event: str, data: dict):
    """Append to audit log list in Redis (last 1000 entries)."""
    entry = json.dumps({"event": event, "ts": datetime.utcnow().isoformat(), **data})
    r.lpush("audit:log", entry)
    r.ltrim("audit:log", 0, 999)

# ─────────────────────────────────────────────
# SLACK HELPERS
# ─────────────────────────────────────────────

async def notify_slack_approval(request_id: str, req_data: dict):
    """Post approval card to the approvals channel."""
    await slack_app.client.chat_postMessage(
        channel=APPROVAL_CHANNEL,
        text=f"New access request from {req_data['developer_id']}",
        blocks=[
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🔐 JIT Access Request"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Developer:*\n`{req_data['developer_id']}`"},
                    {"type": "mrkdwn", "text": f"*Resource:*\n`{req_data['resource_id']}`"},
                    {"type": "mrkdwn", "text": f"*TTL:*\n{req_data['ttl']}s"},
                    {"type": "mrkdwn", "text": f"*Reason:*\n{req_data['reason']}"},
                ]
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "action_id": "jit_approve",
                        "value": request_id
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Deny"},
                        "style": "danger",
                        "action_id": "jit_deny",
                        "value": request_id
                    }
                ]
            }
        ]
    )

async def dm_developer(developer_id: str, message: str):
    slack_id = get_developer_slack_id(developer_id)
    try:
        await slack_app.client.chat_postMessage(channel=slack_id, text=message)
    except Exception:
        pass  # DM failure should not break the main flow

# ─────────────────────────────────────────────
# SLACK ACTIONS
# ─────────────────────────────────────────────

@slack_app.action("jit_approve")
async def handle_approve(ack, body, action):
    await ack()
    request_id = action["value"]
    approver    = body["user"]["name"]

    try:
        req_data = get_request(request_id)
    except HTTPException:
        return

    if req_data["status"] != "pending":
        return  # already handled

    cred = issue_credential(
        request_id   = request_id,
        resource_id  = req_data["resource_id"],
        developer_id = req_data["developer_id"],
        ttl          = req_data["ttl"]
    )

    req_data["status"]      = "approved"
    req_data["approved_by"] = approver
    req_data["approved_at"] = time.time()
    save_request(request_id, req_data)

    log_audit("approved", {"request_id": request_id, "approver": approver})

    expires_str = datetime.fromtimestamp(cred["expires_at"]).strftime("%H:%M:%S UTC")
    await dm_developer(
        req_data["developer_id"],
        f"✅ *Access Approved!*\n"
        f"Resource: `{cred['resource_id']}`\n"
        f"Token: `{cred['token']}`\n"
        f"Permissions: `{', '.join(cred['permissions'])}`\n"
        f"Expires at: *{expires_str}*\n"
        f"_This token auto-expires. Do not share it._"
    )

    # Update Slack message to reflect approval
    await slack_app.client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"✅ Approved by @{approver}",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"✅ *Approved* by `{approver}` — Request `{request_id}`"}
        }]
    )


@slack_app.action("jit_deny")
async def handle_deny(ack, body, action):
    await ack()
    request_id = action["value"]
    denier     = body["user"]["name"]

    try:
        req_data = get_request(request_id)
    except HTTPException:
        return

    req_data["status"]    = "denied"
    req_data["denied_by"] = denier
    req_data["denied_at"] = time.time()
    save_request(request_id, req_data)

    log_audit("denied", {"request_id": request_id, "denier": denier})

    await dm_developer(
        req_data["developer_id"],
        f"❌ *Access Denied*\n"
        f"Resource: `{req_data['resource_id']}`\n"
        f"Denied by: `{denier}`\n"
        f"Contact your team lead if you believe this is an error."
    )

    await slack_app.client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"❌ Denied by @{denier}",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"❌ *Denied* by `{denier}` — Request `{request_id}`"}
        }]
    )

# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check — use this for Docker/K8s probes."""
    try:
        r.ping()
        return {"status": "ok", "redis": "connected", "ts": time.time()}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}")


@app.post("/register-resource", summary="Register a dynamic cloud resource")
async def register_resource(payload: ResourceRegister):
    """
    Called by containers/VMs on startup.
    Resource is auto-removed from Redis when TTL expires (resource destroyed).
    """
    data = {
        "resource_id":   payload.resource_id,
        "type":          payload.resource_type,
        "region":        payload.region,
        "tags":          payload.tags,
        "registered_at": time.time(),
    }
    r.setex(f"resource:{payload.resource_id}", 86400, json.dumps(data))
    log_audit("resource_registered", {"resource_id": payload.resource_id})
    return {"status": "registered", "resource_id": payload.resource_id}


@app.delete("/deregister-resource/{resource_id}", summary="Deregister a resource on teardown")
async def deregister_resource(resource_id: str):
    r.delete(f"resource:{resource_id}")
    log_audit("resource_deregistered", {"resource_id": resource_id})
    return {"status": "deregistered", "resource_id": resource_id}


@app.post("/request-access", summary="Developer requests temporary access")
async def request_access(payload: AccessRequest):
    """
    Developer submits an access request.
    Triggers Slack approval workflow automatically.
    """
    # Check resource exists
    if not r.exists(f"resource:{payload.resource_id}"):
        raise HTTPException(status_code=404,
                            detail=f"Resource '{payload.resource_id}' not found or not registered")

    request_id = secrets.token_hex(8)
    req_data = {
        "request_id":   request_id,
        "developer_id": payload.developer_id,
        "resource_id":  payload.resource_id,
        "reason":       payload.reason,
        "ttl":          payload.ttl,
        "status":       "pending",
        "created_at":   time.time(),
    }
    save_request(request_id, req_data)
    log_audit("access_requested", {"request_id": request_id,
                                    "developer_id": payload.developer_id,
                                    "resource_id": payload.resource_id})

    # Fire Slack notification (non-blocking)
    if SLACK_BOT_TOKEN:
        asyncio.create_task(notify_slack_approval(request_id, req_data))

    return {
        "request_id": request_id,
        "status":     "pending",
        "message":    "Approval request sent to Slack. You will be DM'd when a decision is made."
    }


@app.get("/request/{request_id}", summary="Poll request status")
async def get_request_status(request_id: str):
    """Developer can poll this to check if their request was approved/denied."""
    req_data = get_request(request_id)
    response = {
        "request_id":  request_id,
        "status":      req_data["status"],
        "resource_id": req_data["resource_id"],
        "created_at":  req_data["created_at"],
    }
    if req_data["status"] == "approved":
        response["message"] = "Check your Slack DM for the credential token."
    return response


@app.post("/validate", summary="Validate a credential token")
async def validate_token(payload: ValidateRequest):
    """
    Called by the resource/service to verify the developer's token.
    Returns remaining TTL and permissions on success.
    """
    valid, result = validate_credential(payload.token, payload.resource_id)
    if not valid:
        log_audit("validate_failed", {"resource_id": payload.resource_id, "reason": result})
        raise HTTPException(status_code=401, detail=result)

    remaining_ttl = int(r.ttl(f"cred:{payload.token}"))
    log_audit("validate_success", {
        "developer_id": result["developer_id"],
        "resource_id":  result["resource_id"],
        "ttl_left":     remaining_ttl
    })
    return {
        "valid":        True,
        "developer_id": result["developer_id"],
        "permissions":  result["permissions"],
        "ttl_remaining": remaining_ttl,
        "expires_at":   result["expires_at"],
    }


@app.post("/revoke/{token}", summary="Manually revoke a credential before expiry")
async def revoke_credential(token: str):
    """Immediately delete a credential — emergency revocation."""
    deleted = r.delete(f"cred:{token}")
    if not deleted:
        raise HTTPException(status_code=404, detail="Token not found or already expired")
    log_audit("credential_revoked", {"token_prefix": token[:8]})
    return {"status": "revoked", "message": "Credential deleted immediately"}


@app.get("/audit", summary="View recent audit log")
async def get_audit_log(limit: int = 50):
    """Returns last N audit events."""
    entries = r.lrange("audit:log", 0, limit - 1)
    return {"events": [json.loads(e) for e in entries], "count": len(entries)}


@app.get("/resources", summary="List all registered resources")
async def list_resources():
    keys = r.keys("resource:*")
    resources = []
    for key in keys:
        raw = r.get(key)
        if raw:
            data = json.loads(raw)
            data["ttl_remaining"] = r.ttl(key)
            resources.append(data)
    return {"resources": resources, "count": len(resources)}


# ─────────────────────────────────────────────
# SLACK EVENTS ROUTE (mount on FastAPI)
# ─────────────────────────────────────────────

@app.post("/slack/events")
async def slack_events(req):
    return await slack_handler.handle(req)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)