"""
Phase 12 end-to-end tests:
- Multi-tenant isolation & authorization hardening
- Cross-user access denial
- Ownership enforcement
- Superuser bypass
- Dashboard isolation
- API authorization consistency
- Device/network leakage prevention
"""

import asyncio
import os
import sys
import uuid

import httpx

API_BASE = os.environ.get("MIDSCALE_API_URL", "http://localhost:8000/api/v1")
ADMIN_EMAIL = "admin@midscale.local"
ADMIN_PASS = "admin123"

PASS = 0
FAIL = 0
ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        msg = f"  ✗ {name}: {detail}"
        print(msg)
        ERRORS.append(msg)


async def test_phase12():
    global PASS, FAIL, ERRORS

    print("\n" + "=" * 70)
    print("PHASE 12 END-TO-END TESTS")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=API_BASE, timeout=10) as c:
        # ── Setup: login as admin ──
        print("\n--- Setup: Admin Login ---")
        r = await c.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
        check("admin login", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print("Cannot proceed without admin login")
            return
        admin_token = r.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # ── Setup: verify admin is superuser ──
        r = await c.get("/auth/me", headers=admin_headers)
        check("admin is superuser", r.json().get("is_superuser") is True,
              f"is_superuser={r.json().get('is_superuser')}")

        # ── Setup: create a network as admin ──
        print("\n--- Setup: Admin Creates Network ---")
        net_name = f"admin-net-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": net_name, "subnet": "10.200.0.0/24"}, headers=admin_headers)
        check("admin create network", r.status_code == 201, f"status={r.status_code}")
        admin_network_id = r.json()["id"]
        check("network has owner_id", r.json().get("owner_id") is not None,
              "owner_id missing in response")

        # ── Setup: create a device in admin's network ──
        print("\n--- Setup: Admin Creates Device ---")
        r = await c.post(f"/networks/{admin_network_id}/devices", json={"name": "admin-device"}, headers=admin_headers)
        check("admin create device", r.status_code == 201, f"status={r.status_code}")
        admin_device_id = r.json()["id"]

        # ── Setup: create pre-auth key ──
        r = await c.post(f"/networks/{admin_network_id}/preauth-keys",
                         json={"reusable": True, "expires_in_hours": 1}, headers=admin_headers)
        check("admin create preauth key", r.status_code == 201, f"status={r.status_code}")

        # ── Setup: register two normal users ──
        print("\n--- Setup: Register Normal Users ---")
        user1_email = f"user1-{uuid.uuid4().hex[:8]}@test.local"
        user1_pass = "password123"
        r = await c.post("/auth/register", json={"email": user1_email, "password": user1_pass, "display_name": "User One"})
        check("user1 register", r.status_code == 201, f"status={r.status_code}")
        user1_token = r.json()["access_token"]
        user1_headers = {"Authorization": f"Bearer {user1_token}"}

        user2_email = f"user2-{uuid.uuid4().hex[:8]}@test.local"
        user2_pass = "password456"
        r = await c.post("/auth/register", json={"email": user2_email, "password": user2_pass, "display_name": "User Two"})
        check("user2 register", r.status_code == 201, f"status={r.status_code}")
        user2_token = r.json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # Verify users are NOT superusers
        r = await c.get("/auth/me", headers=user1_headers)
        check("user1 is not superuser", r.json().get("is_superuser") is False)
        r = await c.get("/auth/me", headers=user2_headers)
        check("user2 is not superuser", r.json().get("is_superuser") is False)

        # ═══════════════════════════════════════════════════════════
        # TEST 1: Normal user initially sees zero networks
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 1: Normal user sees zero networks initially")
        print("=" * 70)

        r = await c.get("/networks", headers=user1_headers)
        check("user1 lists 0 networks", len(r.json()) == 0, f"got {len(r.json())} networks")
        check("user1 response is 200", r.status_code == 200)

        r = await c.get("/devices", headers=user1_headers)
        check("user1 lists 0 devices", len(r.json()) == 0, f"got {len(r.json())} devices")

        # ═══════════════════════════════════════════════════════════
        # TEST 2: Normal user cannot access admin's network by ID
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 2: Cross-user network access denial")
        print("=" * 70)

        r = await c.get(f"/networks/{admin_network_id}", headers=user1_headers)
        check("user1 GET admin network returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.put(f"/networks/{admin_network_id}", json={"name": "hacked"}, headers=user1_headers)
        check("user1 PUT admin network returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.delete(f"/networks/{admin_network_id}", headers=user1_headers)
        check("user1 DELETE admin network returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 3: Cross-user device access denial
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 3: Cross-user device access denial")
        print("=" * 70)

        r = await c.get(f"/devices/{admin_device_id}", headers=user1_headers)
        check("user1 GET admin device returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.put(f"/devices/{admin_device_id}", json={"name": "hacked"}, headers=user1_headers)
        check("user1 PUT admin device returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/devices/{admin_device_id}/revoke", headers=user1_headers)
        check("user1 POST revoke admin device returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 4: Cross-user network sub-resource access denial
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 4: Cross-user sub-resource access denial")
        print("=" * 70)

        # Devices sub-resource
        r = await c.get(f"/networks/{admin_network_id}/devices", headers=user1_headers)
        check("user1 list devices in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/networks/{admin_network_id}/devices", json={"name": "hacked-device"}, headers=user1_headers)
        check("user1 create device in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/networks/{admin_network_id}/node-devices", json={"name": "hacked-node"}, headers=user1_headers)
        check("user1 create node device in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # Pre-auth keys
        r = await c.get(f"/networks/{admin_network_id}/preauth-keys", headers=user1_headers)
        check("user1 list preauth keys in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/networks/{admin_network_id}/preauth-keys",
                         json={"reusable": False, "expires_in_hours": 1}, headers=user1_headers)
        check("user1 create preauth key in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # ACLs
        r = await c.get(f"/networks/{admin_network_id}/acls", headers=user1_headers)
        check("user1 list ACLs in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/networks/{admin_network_id}/acls",
                         json={"src_tags": ["tag1"], "dst_tags": ["tag2"]}, headers=user1_headers)
        check("user1 create ACL in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # DNS
        r = await c.get(f"/networks/{admin_network_id}/dns", headers=user1_headers)
        check("user1 list DNS in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/networks/{admin_network_id}/dns",
                         json={"domain": "test.local", "address": "10.200.0.100"}, headers=user1_headers)
        check("user1 create DNS in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # Routes
        r = await c.get(f"/routes/networks/{admin_network_id}", headers=user1_headers)
        check("user1 list routes in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/routes/networks/{admin_network_id}/advertise",
                         json={"prefix": "10.0.0.0/16"}, headers=user1_headers)
        check("user1 advertise route in admin net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 5: User can create and manage their own network
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 5: User can create and manage their own network")
        print("=" * 70)

        user1_net_name = f"user1-net-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": user1_net_name, "subnet": "10.201.0.0/24"}, headers=user1_headers)
        check("user1 create network", r.status_code == 201, f"status={r.status_code}")
        user1_network_id = r.json()["id"]
        check("user1 network has owner_id", r.json().get("owner_id") is not None)

        # User1 can see their own network
        r = await c.get("/networks", headers=user1_headers)
        check("user1 sees 1 network", len(r.json()) == 1, f"got {len(r.json())}")

        r = await c.get(f"/networks/{user1_network_id}", headers=user1_headers)
        check("user1 GET own network returns 200", r.status_code == 200,
              f"status={r.status_code}")

        # User1 can create devices in their network
        r = await c.post(f"/networks/{user1_network_id}/devices",
                         json={"name": "user1-device"}, headers=user1_headers)
        check("user1 create device in own net", r.status_code == 201, f"status={r.status_code}")
        user1_device_id = r.json()["id"]

        r = await c.get(f"/networks/{user1_network_id}/devices", headers=user1_headers)
        check("user1 list devices in own net", r.status_code == 200, f"status={r.status_code}")
        # 1 user-created + 1 __midscale_server__ device
        check("user1 sees 2 devices", len(r.json()) == 2, f"got {len(r.json())}")

        r = await c.get(f"/devices/{user1_device_id}", headers=user1_headers)
        check("user1 GET own device", r.status_code == 200, f"status={r.status_code}")

        # User1 can manage ACLs in own network
        r = await c.post(f"/networks/{user1_network_id}/acls",
                         json={"src_tags": ["tag1"], "dst_tags": ["tag2"]}, headers=user1_headers)
        check("user1 create ACL in own net", r.status_code == 201, f"status={r.status_code}")
        acl_id = r.json()["id"]

        r = await c.put(f"/networks/{user1_network_id}/acls/{acl_id}",
                        json={"priority": 50}, headers=user1_headers)
        check("user1 update ACL in own net", r.status_code == 200, f"status={r.status_code}")

        r = await c.delete(f"/networks/{user1_network_id}/acls/{acl_id}", headers=user1_headers)
        check("user1 delete ACL in own net", r.status_code == 204, f"status={r.status_code}")

        # User1 can manage DNS in own network
        r = await c.post(f"/networks/{user1_network_id}/dns",
                         json={"domain": "test.local", "address": "10.201.0.100"}, headers=user1_headers)
        check("user1 create DNS in own net", r.status_code == 201, f"status={r.status_code}")
        dns_id = r.json()["id"]

        r = await c.delete(f"/networks/{user1_network_id}/dns/{dns_id}", headers=user1_headers)
        check("user1 delete DNS in own net", r.status_code == 204, f"status={r.status_code}")

        # User1 can manage preauth keys in own network
        r = await c.post(f"/networks/{user1_network_id}/preauth-keys",
                         json={"reusable": True, "expires_in_hours": 1}, headers=user1_headers)
        check("user1 create preauth key in own net", r.status_code == 201, f"status={r.status_code}")
        key_id = r.json()["id"]

        r = await c.delete(f"/networks/{user1_network_id}/preauth-keys/{key_id}", headers=user1_headers)
        check("user1 delete preauth key in own net", r.status_code == 204, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 6: User2 cannot see user1's network
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 6: User2 cannot see User1's resources")
        print("=" * 70)

        r = await c.get("/networks", headers=user2_headers)
        check("user2 sees 0 networks", len(r.json()) == 0, f"got {len(r.json())}")

        r = await c.get(f"/networks/{user1_network_id}", headers=user2_headers)
        check("user2 GET user1 network returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.get(f"/networks/{user1_network_id}/devices", headers=user2_headers)
        check("user2 list devices in user1 net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.get(f"/devices/{user1_device_id}", headers=user2_headers)
        check("user2 GET user1 device returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.get(f"/networks/{user1_network_id}/acls", headers=user2_headers)
        check("user2 list ACLs in user1 net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.get(f"/networks/{user1_network_id}/dns", headers=user2_headers)
        check("user2 list DNS in user1 net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.get(f"/routes/networks/{user1_network_id}", headers=user2_headers)
        check("user2 list routes in user1 net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.get(f"/networks/{user1_network_id}/preauth-keys", headers=user2_headers)
        check("user2 list preauth keys in user1 net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        r = await c.post(f"/networks/{user1_network_id}/devices",
                         json={"name": "stolen"}, headers=user2_headers)
        check("user2 create device in user1 net returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 7: Superuser sees all networks and devices
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 7: Superuser sees all resources")
        print("=" * 70)

        r = await c.get("/networks", headers=admin_headers)
        check("admin sees 2+ networks", len(r.json()) >= 2, f"got {len(r.json())}")

        r = await c.get("/devices", headers=admin_headers)
        check("admin sees 2+ devices", len(r.json()) >= 2, f"got {len(r.json())}")

        # Superuser can access user1's network
        r = await c.get(f"/networks/{user1_network_id}", headers=admin_headers)
        check("admin GET user1 network returns 200", r.status_code == 200,
              f"status={r.status_code}")

        # Superuser can access user1's device
        r = await c.get(f"/devices/{user1_device_id}", headers=admin_headers)
        check("admin GET user1 device returns 200", r.status_code == 200,
              f"status={r.status_code}")

        # Superuser can see user1's devices
        r = await c.get(f"/networks/{user1_network_id}/devices", headers=admin_headers)
        check("admin list user1 devices returns 200", r.status_code == 200,
              f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 8: Audit log restricted to superuser
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 8: Audit log access control")
        print("=" * 70)

        r = await c.get("/audit?limit=1", headers=user1_headers)
        check("user1 audit returns 403", r.status_code == 403, f"status={r.status_code}")

        r = await c.get("/audit/actions", headers=user1_headers)
        check("user1 audit actions returns 403", r.status_code == 403, f"status={r.status_code}")

        r = await c.get("/audit?limit=1", headers=admin_headers)
        check("admin audit returns 200", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 9: Health summary restricted to superuser
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 9: Health summary access control")
        print("=" * 70)

        API_ROOT = "http://localhost:8000"
        async with httpx.AsyncClient(base_url=API_ROOT, timeout=10) as root_c:
            r = await root_c.get("/health", headers=user1_headers)
            check("user1 health summary returns 403", r.status_code == 403,
                  f"status={r.status_code}")

            r = await root_c.get("/health", headers=admin_headers)
            check("admin health summary returns 200", r.status_code == 200,
                  f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 10: Device leakage — user1 cannot enumerate devices by brute-force
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 10: Device ID enumeration prevention")
        print("=" * 70)

        # user1 cannot access admin device even with known ID
        r = await c.get(f"/devices/{admin_device_id}", headers=user1_headers)
        check("user1 GET admin device still returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # user2 cannot access user1 device
        r = await c.get(f"/devices/{user1_device_id}", headers=user2_headers)
        check("user2 GET user1 device returns 403", r.status_code == 403,
              f"status={r.status_code}")

        # user1 device list shows only own devices (1 user-created + 1 __midscale_server__)
        r = await c.get("/devices", headers=user1_headers)
        check("user1 devices list has 2 devices", len(r.json()) == 2, f"got {len(r.json())}")

        # user2 device list shows zero
        r = await c.get("/devices", headers=user2_headers)
        check("user2 devices list has 0 devices", len(r.json()) == 0, f"got {len(r.json())}")

        # ═══════════════════════════════════════════════════════════
        # TEST 11: User can update their own network
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 11: User can update own network")
        print("=" * 70)

        r = await c.put(f"/networks/{user1_network_id}",
                        json={"name": "updated-name"}, headers=user1_headers)
        check("user1 update own network", r.status_code == 200, f"status={r.status_code}")
        check("network name updated", r.json().get("name") == "updated-name",
              f"name={r.json().get('name')}")

        # ═══════════════════════════════════════════════════════════
        # TEST 12: User can update their own device
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 12: User can update own device")
        print("=" * 70)

        r = await c.put(f"/devices/{user1_device_id}",
                        json={"name": "updated-device"}, headers=user1_headers)
        check("user1 update own device", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # CLEANUP
        # ═══════════════════════════════════════════════════════════
        print("\n--- Cleanup ---")
        r = await c.delete(f"/networks/{user1_network_id}", headers=user1_headers)
        check("user1 cleanup network", r.status_code == 204, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════════════════
        total = PASS + FAIL
        print("\n" + "=" * 70)
        print(f"RESULTS: {PASS}/{total} passed, {FAIL}/{total} failed")
        print("=" * 70)
        if ERRORS:
            print("\nErrors:")
            for e in ERRORS:
                print(f"  {e}")

        return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(test_phase12())
    sys.exit(0 if success else 1)
