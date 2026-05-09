"""Route advertisement validation logic.

Security-critical: validates advertised routes before accepting them.
Never trust client-advertised routes blindly.
"""

import ipaddress

from fastapi import HTTPException, status


# Subnets that must never be advertised
_FORBIDDEN_PREFIXES: set[str] = {
    "127.0.0.0/8",
    "169.254.0.0/16",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "0.0.0.0/8",
}


def check_safe_prefix(prefix: str, is_exit_node: bool) -> None:
    """Validate an advertised route prefix.

    Raises ``HTTPException`` if the prefix is unsafe or invalid.
    """
    if prefix in _FORBIDDEN_PREFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Route prefix {prefix} is reserved and cannot be advertised",
        )

    if prefix == "0.0.0.0/0":
        if not is_exit_node:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="0.0.0.0/0 can only be advertised as an exit node",
            )
        return

    if prefix == "::/0":
        if not is_exit_node:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="::/0 can only be advertised as an exit node",
            )
        return

    try:
        net = ipaddress.IPv4Network(prefix, strict=False)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CIDR prefix: {e}",
        )

    if net.prefixlen < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Prefix length /{net.prefixlen} is too broad. Minimum is /8.",
        )

    if net.is_private is False and not net.is_loopback:
        from app.config import settings
        if settings.debug:
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Public IP range {prefix} cannot be advertised as a subnet route",
        )


def check_overlap(
    existing_prefixes: list[str], new_prefix: str
) -> str | None:
    """Check if ``new_prefix`` overlaps any existing prefix.

    Returns the overlapping prefix, or ``None`` if no overlap.
    """
    try:
        new_net = ipaddress.IPv4Network(new_prefix, strict=False)
    except ValueError:
        return None

    for existing in existing_prefixes:
        try:
            existing_net = ipaddress.IPv4Network(existing, strict=False)
        except ValueError:
            continue
        if new_net.overlaps(existing_net):
            return existing

    return None
