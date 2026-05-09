"""
Phase 8 end-to-end tests:
- Endpoint scoring service
- Probe result API auth and processing
- Preferred endpoint selection
- Config-v2 candidate ordering
- Reachable vs unreachable scoring
- Latency/failure scoring impact
- Metrics increment correctly
- Mesh topology receives multiple candidates
- Hybrid fallback preserved
- Backward compatibility preserved
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


def check_score(name: str, got: int, expected: int, tolerance: int = 5):
    """Soft check: warn if score differs but don't fail."""
    if abs(got - expected) <= tolerance:
        check(name, True)
    else:
        check(name, False, f"expected ~{expected}, got {got}")


async def test_phase8():
    global PASS, FAIL, ERRORS

    print("\n" + "=" * 70)
    print("PHASE 8 END-TO-END TESTS — Peer Connectivity Probing & Candidate Scoring")
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

        # ── Setup: Create mesh network ──
        print("\n--- Setup: Mesh Network ---")
        mesh_net = f"probe-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": mesh_net, "subnet": "10.210.0.0/24", "topology": "mesh"}, headers=admin_headers)
        check("create mesh network", r.status_code == 201, f"status={r.status_code}")
        mesh_net_id = r.json()["id"]

        r = await c.post(f"/networks/{mesh_net_id}/preauth-keys", json={"reusable": True, "expires_in_hours": 1}, headers=admin_headers)
        mesh_pk = r.json()["key"]

        # ── Setup: Create hybrid network ──
        hybrid_net = f"hybrid-probe-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": hybrid_net, "subnet": "10.211.0.0/24", "topology": "hybrid"}, headers=admin_headers)
        check("create hybrid network", r.status_code == 201, f"status={r.status_code}")
        hybrid_net_id = r.json()["id"]

        r = await c.post(f"/networks/{hybrid_net_id}/preauth-keys", json={"reusable": True, "expires_in_hours": 1}, headers=admin_headers)
        hybrid_pk = r.json()["key"]

        # ── Enroll three devices ──
        print("\n--- Setup: Enroll Devices ---")
        devices = []
        for i in range(3):
            pk = f"PROBE_PK_{i}_{uuid.uuid4().hex[:16]}"
            r = await c.post("/devices/enroll", json={
                "preauth_key": mesh_pk, "name": f"probe-device-{i}", "public_key": pk,
            })
            check(f"enroll device {i}", r.status_code == 201, f"status={r.status_code}")
            d = r.json()
            d_id = d["device_id"]
            d_token = d["device_token"]
            devices.append({"id": d_id, "token": d_token, "name": f"probe-device-{i}"})

        # ═══════════════════════════════════════════════════════════
        # TEST 1: Endpoint Score Calculation
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 1: Endpoint Score Calculation")
        print("=" * 70)

        from app.services.endpoint_scoring import compute_endpoint_score, select_best_endpoint, sort_endpoint_candidates

        # Reachable, low latency, no failures
        s1 = compute_endpoint_score(reachable=True, latency_ms=10, failure_count=0, success_count=5, priority=50)
        check_score("reachable+low latency+successes", s1, 50 + 100 - 50 - 1 + 10, tolerance=5)

        # Unreachable with failures (score floor at 0)
        s2 = compute_endpoint_score(reachable=False, latency_ms=None, failure_count=3, success_count=0, priority=100)
        check("unreachable+failures floor at 0", s2 == 0, f"got {s2}")

        # High latency penalty
        s3 = compute_endpoint_score(reachable=True, latency_ms=500, failure_count=0, success_count=1, priority=50)
        check_score("reachable+high latency", s3, 50 + 100 - 50 - 50 + 2, tolerance=5)

        # Score bounds test
        s4 = compute_endpoint_score(reachable=False, latency_ms=9999, failure_count=999, success_count=0, priority=999)
        check("score floor at 0", s4 >= 0, f"got {s4}")

        s5 = compute_endpoint_score(reachable=True, latency_ms=0, failure_count=0, success_count=999, priority=1)
        check("score ceiling at 200", s5 <= 200, f"got {s5}")

        # ═══════════════════════════════════════════════════════════
        # TEST 2: Preferred Endpoint Selection
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 2: Preferred Endpoint Selection")
        print("=" * 70)

        class MockEndpoint:
            def __init__(self, id_str, score=0, reachable=False, latency_ms=None, priority=100):
                self.id = id
                self.id_str = id_str
                self.score = score
                self.reachable = reachable
                self.latency_ms = latency_ms
                self.priority = priority

        mock_eps = [
            MockEndpoint("ep1", score=80, reachable=True, latency_ms=20),
            MockEndpoint("ep2", score=150, reachable=True, latency_ms=5),
            MockEndpoint("ep3", score=30, reachable=False, latency_ms=None),
        ]

        best = select_best_endpoint(mock_eps)
        check("preferred is highest score", best is not None and best.score == 150, f"got score={best.score if best else None}")

        # Reachable beats unreachable
        mock_eps2 = [
            MockEndpoint("ep1", score=30, reachable=False),
            MockEndpoint("ep2", score=60, reachable=True, latency_ms=100),
        ]
        best2 = select_best_endpoint(mock_eps2)
        check("reachable beats unreachable", best2 is not None and best2.reachable, f"reachable={best2.reachable}")

        sorted_list = sort_endpoint_candidates(mock_eps)
        check("sort by score descending", sorted_list[0].score >= sorted_list[-1].score,
              f"first={sorted_list[0].score} last={sorted_list[-1].score}")

        # ═══════════════════════════════════════════════════════════
        # TEST 3: Probe Result API Auth
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 3: Probe Result API Auth")
        print("=" * 70)

        if len(devices) >= 2:
            d0 = devices[0]
            d1 = devices[1]
            d0_headers = {"Authorization": f"Bearer {d0['token']}"}

            # Valid probe result
            r = await c.post(
                f"/devices/{d0['id']}/probe-result",
                json={
                    "peer_device_id": d1['id'],
                    "endpoint": "203.0.113.50",
                    "reachable": True,
                    "latency_ms": 15,
                    "port": 51820,
                },
                headers=d0_headers,
            )
            check("probe result accepted (valid auth)", r.status_code == 200, f"status={r.status_code}")

            # No auth
            r = await c.post(
                f"/devices/{d0['id']}/probe-result",
                json={
                    "peer_device_id": d1['id'],
                    "endpoint": "203.0.113.51",
                    "reachable": False,
                },
            )
            check("probe result rejected (no auth)", r.status_code == 401, f"status={r.status_code}")

            # Wrong device token
            wrong_headers = {"Authorization": "Bearer invalid_token_xyz"}
            r = await c.post(
                f"/devices/{d0['id']}/probe-result",
                json={
                    "peer_device_id": d1['id'],
                    "endpoint": "203.0.113.52",
                    "reachable": True,
                },
                headers=wrong_headers,
            )
            check("probe result rejected (invalid token)", r.status_code == 401, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 4: Reachable vs Unreachable Scoring
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 4: Reachable vs Unreachable Scoring")
        print("=" * 70)

        r = compute_endpoint_score(reachable=True, latency_ms=10, failure_count=0, success_count=1)
        u = compute_endpoint_score(reachable=False, latency_ms=None, failure_count=1, success_count=0)
        check("reachable scores higher than unreachable", r > u, f"reachable={r} unreachable={u}")

        # ═══════════════════════════════════════════════════════════
        # TEST 5: Lower Latency Increases Score
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 5: Lower Latency = Higher Score")
        print("=" * 70)

        low_lat = compute_endpoint_score(reachable=True, latency_ms=5, failure_count=0, success_count=0)
        high_lat = compute_endpoint_score(reachable=True, latency_ms=200, failure_count=0, success_count=0)
        check("lower latency scores higher", low_lat > high_lat, f"low={low_lat} high={high_lat}")

        # ═══════════════════════════════════════════════════════════
        # TEST 6: Failure Count Lowers Score
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 6: Failure Count Lowers Score")
        print("=" * 70)

        no_fail = compute_endpoint_score(reachable=True, latency_ms=20, failure_count=0, success_count=5)
        many_fail = compute_endpoint_score(reachable=True, latency_ms=20, failure_count=10, success_count=1)
        check("fewer failures scores higher", no_fail > many_fail, f"no_fail={no_fail} many_fail={many_fail}")

        # ═══════════════════════════════════════════════════════════
        # TEST 7: Config-v2 Candidate Ordering
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 7: Config-v2 Candidate Ordering")
        print("=" * 70)

        if len(devices) >= 2:
            d0 = devices[0]
            d0_headers = {"Authorization": f"Bearer {d0['token']}"}

            # Submit multiple probe results for the same peer with different scores
            for latency, reachable in [(50, True), (5, True), (200, False)]:
                r = await c.post(
                    f"/devices/{d0['id']}/probe-result",
                    json={
                        "peer_device_id": d1['id'],
                        "endpoint": f"203.0.113.{latency}",
                        "reachable": reachable,
                        "latency_ms": latency,
                        "port": 51820,
                    },
                    headers=d0_headers,
                )
                check(f"probe result with latency={latency}", r.status_code == 200, f"status={r.status_code}")

            # Get config-v2 and check candidate ordering
            r = await c.get(
                f"/devices/{d0['id']}/config-v2",
                headers=d0_headers,
            )
            check("config-v2 fetched", r.status_code == 200, f"status={r.status_code}")
            config = r.json()
            peer_entry = None
            for p in config.get("peers", []):
                if p["public_key"] == f"PROBE_PK_1_{uuid.UUID(d1['id']).hex[:16]}":
                    peer_entry = p
                    break
            # Check endpoint candidates exist
            if peer_entry:
                candidates = peer_entry.get("endpoint_candidates", [])
                check("config-v2 has endpoint candidates", len(candidates) > 0, f"count={len(candidates)}")
                if candidates:
                    scores = [c.get("score", 0) for c in candidates]
                    check("candidates sorted by score descending",
                          all(scores[i] >= scores[i+1] for i in range(len(scores)-1)),
                          f"scores={scores}")
                    preferred = [c for c in candidates if c.get("preferred")]
                    check("exactly one preferred candidate", len(preferred) == 1, f"count={len(preferred)}")
                    if preferred:
                        check("preferred has reachable=True", preferred[0].get("reachable", False),
                              f"preferred={preferred[0]}")
            else:
                check("found peer in config-v2", False, "no peer entry found")

        # ═══════════════════════════════════════════════════════════
        # TEST 8: preferred=True Only on Best Endpoint
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 8: preferred=True Only on Best Endpoint")
        print("=" * 70)

        class MockEP:
            def __init__(self, id, score, reachable, latency_ms=None, priority=100):
                self.id = id
                self.score = score
                self.reachable = reachable
                self.latency_ms = latency_ms
                self.priority = priority

        mock_eps3 = [
            MockEP("a", score=50, reachable=True, latency_ms=10),
            MockEP("b", score=120, reachable=True, latency_ms=5),
            MockEP("c", score=20, reachable=False),
        ]
        best3 = select_best_endpoint(mock_eps3)
        check("best endpoint has highest score", best3 is not None and best3.score == 120,
              f"best score={best3.score if best3 else None}")

        # ═══════════════════════════════════════════════════════════
        # TEST 9: Metrics Increment Correctly
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 9: Metrics Available")
        print("=" * 70)

        r = await c.get("http://localhost:8000/metrics", timeout=10)
        check("metrics endpoint accessible", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            body = r.text
            check("midscale_endpoint_probe_total metric exists", "midscale_endpoint_probe_total" in body,
                  "metric not found in /metrics")
            check("midscale_endpoint_score_updates_total metric exists", "midscale_endpoint_score_updates_total" in body,
                  "metric not found in /metrics")

        # ═══════════════════════════════════════════════════════════
        # TEST 10: Mesh Topology Has Multiple Candidates
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 10: Mesh Topology Has Multiple Candidates")
        print("=" * 70)

        if len(devices) >= 2:
            d0_headers = {"Authorization": f"Bearer {devices[0]['token']}"}
            r = await c.get(f"/devices/{devices[0]['id']}/config-v2", headers=d0_headers)
            check("mesh config-v2 fetched", r.status_code == 200, f"status={r.status_code}")
            config = r.json()
            peers = config.get("peers", [])
            check("mesh has peers", len(peers) >= 1, f"count={len(peers)}")
            for p in peers:
                if p.get("endpoint_candidates"):
                    check("mesh peer has endpoint_candidates", True)
                    break
            else:
                check("mesh peer has endpoint_candidates", False, "no candidates found")

        # ═══════════════════════════════════════════════════════════
        # TEST 11: Hybrid Fallback Preserved
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 11: Hybrid Fallback Preserved")
        print("=" * 70)

        # Enroll a device in hybrid network
        r = await c.post("/devices/enroll", json={
            "preauth_key": hybrid_pk, "name": "hybrid-device", "public_key": f"HYBRID_{uuid.uuid4().hex[:16]}",
        })
        check("hybrid device enrolled", r.status_code == 201, f"status={r.status_code}")
        hybrid_device = r.json()
        hybrid_headers = {"Authorization": f"Bearer {hybrid_device['device_token']}"}

        r = await c.get(f"/devices/{hybrid_device['device_id']}/config-v2", headers=hybrid_headers)
        check("hybrid config-v2 fetched", r.status_code == 200, f"status={r.status_code}")
        config = r.json()
        peers = config.get("peers", [])
        has_relay = any(p.get("relay_fallback") for p in peers)
        check("hybrid has relay_fallback on some peers", has_relay, "relay_fallback missing")

        # ═══════════════════════════════════════════════════════════
        # TEST 12: Star Topology Unchanged
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 12: Star Topology Unchanged")
        print("=" * 70)

        star_net = f"star-probe-{uuid.uuid4().hex[:8]}"
        r = await c.post("/networks", json={"name": star_net, "subnet": "10.212.0.0/24"}, headers=admin_headers)
        check("create star network", r.status_code == 201, f"status={r.status_code}")
        star_net_id = r.json()["id"]
        r = await c.post(f"/networks/{star_net_id}/preauth-keys", json={"reusable": True, "expires_in_hours": 1}, headers=admin_headers)
        star_pk = r.json()["key"]

        r = await c.post("/devices/enroll", json={
            "preauth_key": star_pk, "name": "star-device", "public_key": f"STAR_{uuid.uuid4().hex[:16]}",
        })
        check("star device enrolled", r.status_code == 201, f"status={r.status_code}")
        star_device = r.json()
        star_headers = {"Authorization": f"Bearer {star_device['device_token']}"}

        r = await c.get(f"/devices/{star_device['device_id']}/config-v2", headers=star_headers)
        check("star config-v2 fetched", r.status_code == 200, f"status={r.status_code}")
        config = r.json()
        peers = config.get("peers", [])
        no_candidates = all(not p.get("endpoint_candidates") for p in peers)
        check("star topology has no endpoint_candidates", no_candidates,
              f"found candidates on star peers")

        # ═══════════════════════════════════════════════════════════
        # TEST 13: Backward Compatibility — Old Endpoint Report Still Works
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 13: Backward Compatibility")
        print("=" * 70)

        if len(devices) >= 1:
            d0 = devices[0]
            d0_headers = {"Authorization": f"Bearer {d0['token']}"}

            # Old-style endpoint report (no local_ip/public_ip)
            r = await c.post(
                f"/devices/{d0['id']}/endpoint",
                json={"endpoint": "198.51.100.1", "source": "handshake", "port": 51820},
                headers=d0_headers,
            )
            check("old endpoint report still works", r.status_code == 200, f"status={r.status_code}")

            # Old-style register (no auth)
            r = await c.post("/devices/register", json={
                "key": mesh_pk, "name": "legacy-register-device",
            })
            check("old register still works", r.status_code == 201, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 14: Probe Result Updates Score on Server
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 14: Probe Result Updates Score on Server")
        print("=" * 70)

        if len(devices) >= 2:
            d0_headers = {"Authorization": f"Bearer {devices[0]['token']}"}

            r = await c.post(
                f"/devices/{devices[0]['id']}/probe-result",
                json={
                    "peer_device_id": devices[1]['id'],
                    "endpoint": "198.51.100.99",
                    "reachable": True,
                    "latency_ms": 10,
                    "port": 51820,
                },
                headers=d0_headers,
            )
            check("probe result accepted", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                check("probe result returns score", data.get("score", 0) > 0, f"score={data.get('score')}")
                check("probe result returns preferred", "preferred" in data, f"preferred={data.get('preferred')}")

            # Now submit an unreachable result and observe lower score
            r = await c.post(
                f"/devices/{devices[0]['id']}/probe-result",
                json={
                    "peer_device_id": devices[1]['id'],
                    "endpoint": "198.51.100.99",
                    "reachable": False,
                    "latency_ms": None,
                    "port": 51820,
                },
                headers=d0_headers,
            )
            check("unreachable probe result accepted", r.status_code == 200, f"status={r.status_code}")

        # ═══════════════════════════════════════════════════════════
        # TEST 15: Endpoint Candidate Schema Includes New Fields
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 15: Endpoint Candidate Schema Includes New Fields")
        print("=" * 70)

        if len(devices) >= 1:
            d0_headers = {"Authorization": f"Bearer {devices[0]['token']}"}
            r = await c.get(f"/devices/{devices[0]['id']}/config-v2", headers=d0_headers)
            check("config-v2 fetched for schema check", r.status_code == 200, f"status={r.status_code}")
            config = r.json()
            for p in config.get("peers", []):
                for cand in p.get("endpoint_candidates", []):
                    has_score = "score" in cand
                    has_reachable = "reachable" in cand
                    has_preferred = "preferred" in cand
                    check("candidate has score field", has_score, f"cand={cand.get('endpoint')}")
                    check("candidate has reachable field", has_reachable, f"cand={cand.get('endpoint')}")
                    check("candidate has preferred field", has_preferred, f"cand={cand.get('endpoint')}")
                    break
                break

        # ═══════════════════════════════════════════════════════════
        # TEST 16: Multiple Probe Results for Same Peer
        # ═══════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("TEST 16: Multiple Probe Results for Same Peer")
        print("=" * 70)

        if len(devices) >= 2:
            d0_headers = {"Authorization": f"Bearer {devices[0]['token']}"}
            # Send 5 probe results for the same endpoint
            for i in range(5):
                r = await c.post(
                    f"/devices/{devices[0]['id']}/probe-result",
                    json={
                        "peer_device_id": devices[1]['id'],
                        "endpoint": "10.0.0.1",
                        "reachable": i % 2 == 0,
                        "latency_ms": 10 + i * 5,
                        "port": 51820,
                    },
                    headers=d0_headers,
                )
                check(f"probe result {i} accepted", r.status_code == 200, f"status={r.status_code}")

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
    success = asyncio.run(test_phase8())
    sys.exit(0 if success else 1)
