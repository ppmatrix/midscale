"""Endpoint scoring and candidate selection service.

Computes scores for endpoint candidates based on reachability, latency,
failure/success counts, and priority. Used to select the best endpoint
for peer-to-peer connections in mesh/hybrid topologies.

Scoring formula:

    score = BASE_SCORE
        + (100 if reachable else 0)
        - min(priority, 100)
        - (latency_ms // 10)     # penalty per 10ms
        - (failure_count * 5)    # penalty per failure
        + (success_count * 2)    # bonus per success

Score floor: 0
Score ceiling: 200

A higher score means a better endpoint.
"""

from typing import Optional

BASE_SCORE = 50
SCORE_MAX = 200


def compute_endpoint_score(
    reachable: bool = False,
    latency_ms: Optional[int] = None,
    failure_count: int = 0,
    success_count: int = 0,
    priority: int = 100,
) -> int:
    score = BASE_SCORE
    if reachable:
        score += 100
    score -= min(priority, 100)
    if latency_ms is not None:
        score -= latency_ms // 10
    score -= failure_count * 5
    score += success_count * 2
    return max(0, min(score, SCORE_MAX))


def select_best_endpoint(endpoints: list) -> Optional[object]:
    """Select the best endpoint from a list of endpoint objects.

    Uses score (descending), then reachable, then latency (ascending),
    then priority (ascending) as tiebreakers.
    """
    if not endpoints:
        return None
    scored = sorted(
        endpoints,
        key=lambda e: (
            getattr(e, "score", 0),
            1 if getattr(e, "reachable", False) else 0,
            -(getattr(e, "latency_ms", 9999) or 9999),
            -(getattr(e, "priority", 100)),
        ),
        reverse=True,
    )
    return scored[0]


def sort_endpoint_candidates(endpoints: list) -> list:
    """Sort endpoints by score descending for config-v2 candidate ordering."""
    return sorted(
        endpoints,
        key=lambda e: (
            getattr(e, "score", 0),
            1 if getattr(e, "reachable", False) else 0,
            -(getattr(e, "latency_ms", 9999) or 9999),
            -(getattr(e, "priority", 100)),
        ),
        reverse=True,
    )
