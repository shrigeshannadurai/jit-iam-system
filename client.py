import argparse
import requests
import time
import sys

BASE_URL = "http://localhost:8000"

def register_resource(resource_id, resource_type):
    print(f"[*] Registering resource {resource_id} ({resource_type})...")
    res = requests.post(f"{BASE_URL}/register-resource", json={
        "resource_id": resource_id,
        "resource_type": resource_type,
        "tags": {"env": "demo"}
    })
    print(res.json())

def request_access(developer_id, resource_id, reason):
    print(f"[*] Requesting access for {developer_id} to {resource_id}...")
    res = requests.post(f"{BASE_URL}/request-access", json={
        "developer_id": developer_id,
        "resource_id": resource_id,
        "reason": reason,
        "ttl": 3600
    })
    res_json = res.json()
    print(res_json)
    return res_json.get("request_id")

def check_status(request_id):
    print(f"[*] Checking status of request {request_id}...")
    res = requests.get(f"{BASE_URL}/request/{request_id}")
    print(res.json())

def validate_token(token, resource_id):
    print(f"[*] Validating token...")
    res = requests.post(f"{BASE_URL}/validate", json={
        "token": token,
        "resource_id": resource_id
    })
    print(res.status_code, res.json())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JIT IAM Demo Client")
    subparsers = parser.add_subparsers(dest="action")

    p_reg = subparsers.add_parser("register", help="Register a resource")
    p_reg.add_argument("resource_id")
    p_reg.add_argument("type", default="vm", nargs="?")

    p_req = subparsers.add_parser("request", help="Request access")
    p_req.add_argument("developer_id")
    p_req.add_argument("resource_id")
    p_req.add_argument("reason")

    p_stat = subparsers.add_parser("status", help="Check request status")
    p_stat.add_argument("request_id")

    p_val = subparsers.add_parser("validate", help="Validate access token")
    p_val.add_argument("token")
    p_val.add_argument("resource_id")

    args = parser.parse_args()

    try:
        if args.action == "register":
            register_resource(args.resource_id, args.type)
        elif args.action == "request":
            request_access(args.developer_id, args.resource_id, args.reason)
        elif args.action == "status":
            check_status(args.request_id)
        elif args.action == "validate":
            validate_token(args.token, args.resource_id)
        else:
            parser.print_help()
    except requests.exceptions.ConnectionError:
        print("[!] Error: Could not connect to API. Is it running on localhost:8000?")
        sys.exit(1)
