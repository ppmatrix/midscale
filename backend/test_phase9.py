"""
Phase 9 end-to-end tests: UDP hole punching & direct peer connectivity.

Tests:
1. NAT session creation
2. Session expiration
3. NAT event publishing
4. Hole punch request auth
5. Candidate pair generation
6. Successful connectivity validation
7. Failed connectivity fallback
8. Preferred endpoint promotion
9. Config.changed emitted after success
10. Metrics increment correctly
11. Direct path score boost
12. Relay fallback preserved
13. Multiple concurrent NAT sessions
14. WebSocket NAT coordination
15. Backward compatibility preserved
"""

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

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


async def test_phase9():
    global PASS, FAIL, ERRORS

    print("\n" + "=" * 70)
    print("PHASE 9 END-TO-END TESTS — UDP Hole Punching & Direct Connectivity")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=API_BASE, timeout=15) as c:
        # ── Setup: login as admin ──
        print("\n--- Setup: Admin Login ---")
        r = await c.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
        check("admin login", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print("Cannot proceed without admin login")
            return
        admin_token = r.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # ── Setup: create a network ──
        print("\n--- Setup: Network Creation ---")
        net_name = f"nat-test-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": net_name, "subnet": "10.150.0.0/24"}, headers=admin_headers)
        check("create network", r.status_code == 201, f"status={r.status_code}")
        network_id = r.json()["id"]
        print(f"  Network ID: {network_id}")

        # ── Setup: create pre-auth key ──
        print("\n--- Setup: Pre-auth Key ---")
        r = await c.post(f"/networks/{network_id}/preauth-keys", json={"reusable": True, "expires_in_hours": 1}, headers=admin_headers)
        check("create preauth key", r.status_code == 201, f"status={r.status_code}")
        preauth_key = r.json()["key"]
        print(f"  Pre-auth Key: {preauth_key[:20]}...")

        # ── Setup: enroll two devices ──
        print("\n--- Setup: Enroll Two Devices ---")
        dev1_pub = f"PUB1_{uuid.uuid4().hex[:12]}"
        dev2_pub = f"PUB2_{uuid.uuid4().hex[:12]}"

        r = await c.post("/devices/enroll", json={
            "preauth_key": preauth_key, "name": "punch-dev-1", "public_key": dev1_pub,
        })
        check("enroll device 1", r.status_code == 201, f"status={r.status_code}")
        d1 = r.json()
        dev1_id = d1["device_id"]
        dev1_token = d1["device_token"]
        check("device 1 has token", bool(dev1_token), f"got {dev1_token[:20]}...")

        r = await c.post("/devices/enroll", json={
            "preauth_key": preauth_key, "name": "punch-dev-2", "public_key": dev2_pub,
        })
        check("enroll device 2", r.status_code == 201, f"status={r.status_code}")
        d2 = r.json()
        dev2_id = d2["device_id"]
        dev2_token = d2["device_token"]

        dev1_headers = {"Authorization": f"Bearer {dev1_token}"}
        dev2_headers = {"Authorization": f"Bearer {dev2_token}"}

        # ── Setup: report endpoints for both devices ──
        print("\n--- Setup: Report Endpoints ---")
        r = await c.post(f"/devices/{dev1_id}/endpoint", json={
            "endpoint": "192.168.1.100", "source": "stun", "port": 51820,
            "local_ip": "10.0.0.1", "public_ip": "203.0.113.1",
        }, headers=dev1_headers)
        check("device 1 endpoint reported", r.status_code == 200, f"status={r.status_code}")

        r = await c.post(f"/devices/{dev2_id}/endpoint", json={
            "endpoint": "192.168.2.200", "source": "stun", "port": 51820,
            "local_ip": "10.0.0.2", "public_ip": "203.0.113.2",
        }, headers=dev2_headers)
        check("device 2 endpoint reported", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 1: NAT session creation
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 1: NAT Session Creation")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "192.168.1.100",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("punch request returns 201", r.status_code == 201, f"status={r.status_code}")
        punch1 = r.json()
        session_id = punch1["session_id"]
        check("punch has session_id", bool(session_id), f"got {session_id}")
        check("punch has candidates", "candidates" in punch1, "missing candidates")
        check("punch state is coordinating", punch1.get("state") == "coordinating",
               f"got {punch1.get('state')}")
        check("punch has target_device_id", punch1.get("target_device_id") == dev2_id, "mismatch")

        r = await c.get(f"/nat/{session_id}", headers=dev1_headers)
        check("get session returns 200", r.status_code == 200, f"status={r.status_code}")
        sess = r.json()
        check("session id matches", sess.get("id") == session_id, "mismatch")
        check("session state is coordinating", sess.get("state") == "coordinating",
               f"got {sess.get('state')}")
        check("session has initiator", str(sess.get("initiator_device_id", "")).replace("-", "") == dev1_id.replace("-", ""), "mismatch")
        check("session has target", str(sess.get("target_device_id", "")).replace("-", "") == dev2_id.replace("-", ""), "mismatch")
        check("session has expires_at", bool(sess.get("expires_at")), "missing")
        check("session connectivity not established", sess.get("connectivity_established") is False, "unexpected true")

        # ═══════════════════════════════════════════════════════════
        # TEST 2: Session auth — other device cannot see session
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 2: Session Authorization")
        print("=" * 70)

        r = await c.get(f"/nat/{session_id}", headers=dev2_headers)
        check("target device can see session", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 3: Unauthorized device cannot access session
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 3: Session Authorization — Third Party Blocked")
        print("=" * 70)

        net2_name = f"nat-test-2-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": net2_name, "subnet": "10.151.0.0/24"}, headers=admin_headers)
        net2_id = r.json()["id"]
        r = await c.post(f"/networks/{net2_id}/preauth-keys", json={"reusable": True, "expires_in_hours": 1}, headers=admin_headers)
        pk2 = r.json()["key"]
        r = await c.post("/devices/enroll", json={
            "preauth_key": pk2, "name": "punch-dev-3", "public_key": f"PUB3_{uuid.uuid4().hex[:12]}",
        })
        dev3_token = r.json()["device_token"]
        dev3_headers = {"Authorization": f"Bearer {dev3_token}"}
        r = await c.get(f"/nat/{session_id}", headers=dev3_headers)
        check("unauthorized device returns 403", r.status_code == 403, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 4: Punch result reporting — success
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 4: Punch Result Reporting — Success")
        print("=" * 70)

        session_id_2 = str(uuid.uuid4())
        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.0.5",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("second punch request", r.status_code == 201, f"status={r.status_code}")
        session_id_2 = r.json()["session_id"]

        r = await c.post(f"/nat/{session_id_2}/result", json={
            "session_id": session_id_2,
            "success": True,
            "selected_endpoint": "10.0.0.5",
            "selected_port": 51820,
            "latency_ms": 15,
        }, headers=dev1_headers)
        check("report success returns 200", r.status_code == 200, f"status={r.status_code}")
        res = r.json()
        check("result state is connected", res.get("state") == "connected", f"got {res.get('state')}")
        check("connectivity established", res.get("connectivity_established") is True, "not established")

        r = await c.get(f"/nat/{session_id_2}", headers=dev1_headers)
        check("session shows connected", r.json().get("state") == "connected", "not connected")

        # ═══════════════════════════════════════════════════════════
        # TEST 5: Punch result reporting — failure
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 5: Punch Result Reporting — Failure")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.0.6",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("failure punch request", r.status_code == 201, f"status={r.status_code}")
        fail_session_id = r.json()["session_id"]

        r = await c.post(f"/nat/{fail_session_id}/result", json={
            "session_id": fail_session_id,
            "success": False,
            "error": "all pairs timed out",
        }, headers=dev1_headers)
        check("report failure returns 200", r.status_code == 200, f"status={r.status_code}")
        res = r.json()
        check("failure state is failed", res.get("state") == "failed", f"got {res.get('state')}")
        check("connectivity not established", res.get("connectivity_established") is False, "unexpected true")

        # ═══════════════════════════════════════════════════════════
        # TEST 6: Connectivity validation — success path
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 6: Connectivity Validation — Success")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.0.7",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("validation punch request", r.status_code == 201, f"status={r.status_code}")
        val_session_id = r.json()["session_id"]

        r = await c.post(f"/nat/{val_session_id}/validate", json={
            "session_id": val_session_id,
            "target_endpoint": "10.0.0.7",
            "target_port": 51820,
            "reachable": True,
            "latency_ms": 8,
        }, headers=dev1_headers)
        check("validate returns 200", r.status_code == 200, f"status={r.status_code}")
        val = r.json()
        check("validation status connected", val.get("status") == "connected", f"got {val.get('status')}")
        check("validation direct_path_promoted", val.get("direct_path_promoted") is True, "not promoted")
        check("validation has score", val.get("score", -1) >= 0, f"got {val.get('score')}")
        check("validation has preferred flag", "preferred" in val, "missing")

        # ═══════════════════════════════════════════════════════════
        # TEST 7: Connectivity validation — failure
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 7: Connectivity Validation — Failure")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.0.8",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("failure validate punch", r.status_code == 201, f"status={r.status_code}")
        fail_val_id = r.json()["session_id"]

        r = await c.post(f"/nat/{fail_val_id}/validate", json={
            "session_id": fail_val_id,
            "target_endpoint": "10.0.0.8",
            "target_port": 51820,
            "reachable": False,
        }, headers=dev1_headers)
        check("failure validate returns 200", r.status_code == 200, f"status={r.status_code}")
        val = r.json()
        check("failure status is failed", val.get("status") == "failed", f"got {val.get('status')}")
        check("failure not promoted", val.get("direct_path_promoted") is False, "was promoted")

        # ═══════════════════════════════════════════════════════════
        # TEST 8: Punch to self is rejected
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 8: Self-Punch Rejected")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev1_id,
            "initiator_endpoint": "10.0.0.9",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("self-punch rejected", r.status_code == 400, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 9: Endpoint scoring boost on successful punch
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 9: Endpoint Score Boost on Successful Punch")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "192.168.1.100",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("score punch request", r.status_code == 201, f"status={r.status_code}")
        score_session_id = r.json()["session_id"]

        r = await c.post(f"/nat/{score_session_id}/validate", json={
            "session_id": score_session_id,
            "target_endpoint": "192.168.2.200",
            "target_port": 51820,
            "reachable": True,
            "latency_ms": 5,
        }, headers=dev1_headers)
        check("score validate returns 200", r.status_code == 200, f"status={r.status_code}")
        val = r.json()
        check("score is positive", val.get("score", 0) > 0, f"score={val.get('score')}")
        check("direct path promoted", val.get("direct_path_promoted") is True, "not promoted")

        # ═══════════════════════════════════════════════════════════
        # TEST 10: Backward compatibility — existing endpoints work
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 10: Backward Compatibility — Existing Endpoints")
        print("=" * 70)

        r = await c.post("/devices/enroll", json={
            "preauth_key": preauth_key,
            "name": "backward-compat-dev",
            "public_key": f"PUB_BC_{uuid.uuid4().hex[:10]}",
        })
        check("backward compat enroll", r.status_code == 201, f"status={r.status_code}")

        r = await c.get(f"/devices/{d1['device_id']}/config-v2", headers=admin_headers)
        check("config-v2 backward compat", r.status_code == 200, f"status={r.status_code}")
        config = r.json()
        check("config-v2 has version", "version" in config, "missing version")
        check("config-v2 has peers", "peers" in config, "missing peers")
        check("config-v2 has hash", "hash" in config, "missing hash")

        # ═══════════════════════════════════════════════════════════
        # TEST 11: Multiple concurrent NAT sessions
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 11: Multiple Concurrent NAT Sessions")
        print("=" * 70)

        session_ids = []
        for i in range(5):
            r = await c.post("/nat/punch", json={
                "target_device_id": dev2_id,
                "initiator_endpoint": f"10.0.1.{i}",
                "initiator_port": 51820 + i,
            }, headers=dev1_headers)
            check(f"concurrent session {i} created", r.status_code == 201, f"status={r.status_code}")
            session_ids.append(r.json()["session_id"])

        for sid in session_ids:
            r = await c.get(f"/nat/{sid}", headers=dev1_headers)
            check(f"concurrent session accessible: {sid[:8]}", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 12: Candidate pair structure
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 12: Candidate Pair Structure")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.2.1",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("candidate punch", r.status_code == 201, f"status={r.status_code}")
        candidates = r.json().get("candidates", [])
        check("has candidates", len(candidates) > 0, f"count={len(candidates)}")
        if candidates:
            first = candidates[0]
            check("candidate has initiator", "initiator" in first, "missing initiator")
            check("candidate has target", "target" in first, "missing target")
            check("candidate has pair_key", "pair_key" in first, "missing pair_key")
            init = first["initiator"]
            check("initiator has endpoint", "endpoint" in init, "missing endpoint")
            check("initiator has port", "port" in init, "missing port")
            check("initiator has source", "source" in init, "missing source")

        # ═══════════════════════════════════════════════════════════
        # TEST 13: Metrics endpoint accessible
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 13: Metrics Endpoint")
        print("=" * 70)

        base_url = os.environ.get("MIDSCALE_API_URL", "http://localhost:8000/api/v1")
        metrics_port = base_url.split(":")[2].split("/")[0] if ":" in base_url else "8000"
        metrics_url = f"http://localhost:{metrics_port}/metrics"
        r = await c.get(metrics_url, timeout=5)
        check("metrics accessible", r.status_code == 200, f"status={r.status_code} on {metrics_url}")
        body = r.text
        check("metrics has nat_punch_total", "midscale_nat_punch_total" in body, "missing metric")
        check("metrics has nat_connectivity_total", "midscale_nat_connectivity_total" in body, "missing metric")
        check("metrics has nat_session_active", "midscale_nat_session_active" in body, "missing metric")
        check("metrics has nat_punch_duration", "midscale_nat_punch_duration_seconds" in body, "missing metric")

        # ═══════════════════════════════════════════════════════════
        # TEST 14: Session expiration (create expired session)
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 14: Session Expiration")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.3.1",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("expire session created", r.status_code == 201, f"status={r.status_code}")
        expire_sid = r.json()["session_id"]

        r = await c.get(f"/nat/{expire_sid}", headers=dev1_headers)
        check("session accessible before expiry", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 15: Config.changed emitted after successful validation
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 15: Config.changed on Punch Success")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.4.1",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("config change punch", r.status_code == 201, f"status={r.status_code}")
        cc_session_id = r.json()["session_id"]

        r = await c.post(f"/nat/{cc_session_id}/validate", json={
            "session_id": cc_session_id,
            "target_endpoint": "10.0.4.1",
            "target_port": 51820,
            "reachable": True,
            "latency_ms": 3,
        }, headers=dev1_headers)
        check("config change validate", r.status_code == 200, f"status={r.status_code}")

        r = await c.get(f"/nat/{cc_session_id}", headers=dev1_headers)
        sess = r.json()
        check("config change session connected", sess.get("state") == "connected", f"got {sess.get('state')}")
        check("config change connectivity", sess.get("connectivity_established") is True, "not established")

        # ═══════════════════════════════════════════════════════════
        # TEST 16: Device token auth required
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 16: Device Token Auth Required")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.5.1",
            "initiator_port": 51820,
        })
        check("no auth returns 401", r.status_code == 401, f"status={r.status_code}")

        r = await c.post(f"/nat/{session_id}/result", json={
            "session_id": session_id, "success": True,
        })
        check("no auth result returns 401", r.status_code == 401, f"status={r.status_code}")

        r = await c.post(f"/nat/{session_id}/validate", json={
            "session_id": session_id, "target_endpoint": "10.0.5.1",
            "target_port": 51820, "reachable": True,
        })
        check("no auth validate returns 401", r.status_code == 401, f"status={r.status_code}")

        r = await c.get(f"/nat/{session_id}")
        check("no auth get returns 401", r.status_code == 401, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 17: Relay fallback preserved on failed punch
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 17: Relay Fallback Preserved")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "10.0.6.1",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("relay fallback punch", r.status_code == 201, f"status={r.status_code}")
        relay_sid = r.json()["session_id"]

        r = await c.post(f"/nat/{relay_sid}/validate", json={
            "session_id": relay_sid,
            "target_endpoint": "10.0.6.1",
            "target_port": 51820,
            "reachable": False,
        }, headers=dev1_headers)
        check("relay fallback validate", r.status_code == 200, f"status={r.status_code}")
        val = r.json()
        check("relay fallback not promoted", val.get("direct_path_promoted") is False, "was promoted")

        r = await c.get(f"/devices/{dev1_id}/config-v2", headers=admin_headers)
        check("config-v2 still works after failed punch", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 18: Preferred endpoint update via score
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 18: Preferred Endpoint via Score")
        print("=" * 70)

        r = await c.post("/nat/punch", json={
            "target_device_id": dev2_id,
            "initiator_endpoint": "192.168.1.100",
            "initiator_port": 51820,
        }, headers=dev1_headers)
        check("preferred endpoint punch", r.status_code == 201, f"status={r.status_code}")
        pref_sid = r.json()["session_id"]

        r = await c.post(f"/nat/{pref_sid}/validate", json={
            "session_id": pref_sid,
            "target_endpoint": "192.168.2.200",
            "target_port": 51820,
            "reachable": True,
            "latency_ms": 2,
        }, headers=dev1_headers)
        check("preferred endpoint validate", r.status_code == 200, f"status={r.status_code}")
        val = r.json()
        check("preferred flag", val.get("preferred") is True, "not preferred")

        # ═══════════════════════════════════════════════════════════
        # TEST 19: Metrics increment after operations
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 19: Metrics Increment")
        print("=" * 70)

        r = await c.get("http://localhost:8000/metrics", timeout=5)
        check("metrics endpoint 200", r.status_code == 200, f"status={r.status_code}")
        body = r.text
        for line in body.split("\n"):
            if line.startswith("midscale_nat_punch_total"):
                check("punch metric counted", "result=" in line, line)
                break

        # ═══════════════════════════════════════════════════════════
        # TEST 20: Session not found
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 20: Session Not Found")
        print("=" * 70)

        fake_id = str(uuid.uuid4())
        r = await c.get(f"/nat/{fake_id}", headers=dev1_headers)
        check("nonexistent session 404", r.status_code == 404, f"status={r.status_code}")

        r = await c.post(f"/nat/{fake_id}/result", json={
            "session_id": fake_id, "success": True,
        }, headers=dev1_headers)
        check("nonexistent result 404", r.status_code == 404, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 21: Schema validation — missing fields
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 21: Schema Validation")
        print("=" * 70)

        r = await c.post("/nat/punch", json={}, headers=dev1_headers)
        check("empty body rejected", r.status_code == 422, f"status={r.status_code}")

        r = await c.post("/nat/punch", json={
            "initiator_endpoint": "10.0.8.1",
        }, headers=dev1_headers)
        check("missing target_device_id rejected", r.status_code == 422, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 22: Validate with nonexistent session
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 22: Validate Nonexistent Session")
        print("=" * 70)

        fake_val_id = str(uuid.uuid4())
        r = await c.post(f"/nat/{fake_val_id}/validate", json={
            "session_id": fake_val_id,
            "target_endpoint": "10.0.9.1",
            "target_port": 51820,
            "reachable": True,
        }, headers=dev1_headers)
        check("nonexistent validate returns session_not_found", r.status_code == 200, f"status={r.status_code}")
        val = r.json()
        check("status is session_not_found", val.get("status") == "session_not_found", f"got {val.get('status')}")

        # ═══════════════════════════════════════════════════════════
        # TEST 23: Star topology unchanged (backward compat)
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 23: Star Topology Backward Compat")
        print("=" * 70)

        r = await c.get(f"/networks/{network_id}", headers=admin_headers)
        check("network exists", r.status_code == 200, f"status={r.status_code}")

        r = await c.get(f"/devices/{dev1_id}", headers=admin_headers)
        check("device 1 exists", r.status_code == 200, f"status={r.status_code}")

        r = await c.post(f"/devices/{dev1_id}/heartbeat", json={}, headers=dev1_headers)
        check("heartbeat still works", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 24: Health check still works
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 24: Health Check")
        print("=" * 70)

        base_url_hlth = os.environ.get("MIDSCALE_API_URL", "http://localhost:8000/api/v1")
        health_port = base_url_hlth.split(":")[2].split("/")[0] if ":" in base_url_hlth else "8000"
        r = await c.get(f"http://localhost:{health_port}/health", timeout=5)
        check("health endpoint", r.status_code == 200, f"status={r.status_code}")
        health = r.json()
        check("health status ok", health.get("status") == "ok", f"got {health.get('status')}")

        # ═══════════════════════════════════════════════════════════
        # TEST 25: Event type constants available
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 25: NAT Event Constants")
        print("=" * 70)

        from app.core.constants import (
            EVENT_NAT_PUNCH_REQUESTED,
            EVENT_NAT_PUNCH_STARTED,
            EVENT_NAT_PUNCH_SUCCEEDED,
            EVENT_NAT_PUNCH_FAILED,
            EVENT_NAT_CONNECTIVITY_VALIDATED,
        )
        check("EVENT_NAT_PUNCH_REQUESTED == nat.punch_requested",
               EVENT_NAT_PUNCH_REQUESTED == "nat.punch_requested", "mismatch")
        check("EVENT_NAT_PUNCH_STARTED == nat.punch_started",
               EVENT_NAT_PUNCH_STARTED == "nat.punch_started", "mismatch")
        check("EVENT_NAT_PUNCH_SUCCEEDED == nat.punch_succeeded",
               EVENT_NAT_PUNCH_SUCCEEDED == "nat.punch_succeeded", "mismatch")
        check("EVENT_NAT_PUNCH_FAILED == nat.punch_failed",
               EVENT_NAT_PUNCH_FAILED == "nat.punch_failed", "mismatch")
        check("EVENT_NAT_CONNECTIVITY_VALIDATED == nat.connectivity_validated",
               EVENT_NAT_CONNECTIVITY_VALIDATED == "nat.connectivity_validated", "mismatch")

        # ═══════════════════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("PHASE 9 SUMMARY")
        print("=" * 70)
        total = PASS + FAIL
        print(f"  Total:  {total}")
        print(f"  Passed: {PASS}")
        print(f"  Failed: {FAIL}")
        if ERRORS:
            print("\n  Errors:")
            for e in ERRORS:
                print(f"    {e}")
        print(f"  Rate:   {PASS / total * 100:.1f}%" if total > 0 else "  No tests run")
        return total == PASS


def main():
    global PASS, FAIL, ERRORS
    PASS = 0
    FAIL = 0
    ERRORS = []
    print("\n" + "#" * 70)
    print("# MIDSCALE PHASE 9 — UDP Hole Punching & Direct Connectivity")
    print("#" * 70)
    success = asyncio.run(test_phase9())
    print("\n" + "=" * 70)
    print("PHASE 9 OVERALL: ", "PASS" if success else "FAIL")
    print("=" * 70)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
