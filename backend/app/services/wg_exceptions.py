class WireGuardError(Exception):
    """Base exception for all WireGuard-related errors."""


class WireGuardInterfaceNotFound(WireGuardError):
    """The specified WireGuard interface does not exist on the system."""

    def __init__(self, interface: str):
        self.interface = interface
        super().__init__(f"WireGuard interface not found: {interface}")


class WireGuardCommandError(WireGuardError):
    """The wg CLI command returned a non-zero exit code."""

    def __init__(self, command: str, return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__(
            f"wg command failed (exit {return_code}): {command}\n{stderr}"
        )


class WireGuardPeerNotFound(WireGuardError):
    """The specified peer was not found on the interface."""

    def __init__(self, interface: str, public_key: str):
        self.interface = interface
        self.public_key = public_key
        super().__init__(
            f"Peer {public_key[:16]}... not found on interface {interface}"
        )


class WireGuardKeyError(WireGuardError):
    """Invalid WireGuard key format or content."""


class WireGuardConfigurationError(WireGuardError):
    """Invalid configuration for WireGuard operation."""
