from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Midscale"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://midscale:midscale@localhost:5432/midscale"
    redis_url: str = ""

    secret_key: str = "change-me-to-a-real-secret-in-production"
    encryption_key: str = ""
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    wireguard_interface: str = "wg0"
    wireguard_port: int = 51820
    wireguard_server_endpoint: str = ""
    wireguard_binary: str = "wg"
    wg_controller_interval_seconds: int = 30
    wg_controller_enabled: bool = True
    wireguard_topology: str = "star"

    dns_enabled: bool = False
    dns_domain: str = "wg.midscale"
    dns_zones_path: str = "/etc/coredns/zones"
    dns_coredns_reload_cmd: str = ""
    dns_default_ttl: int = 300

    stun_enabled: bool = True
    stun_port: int = 3478
    stun_host: str = "0.0.0.0"

    relay_enabled: bool = True
    relay_host: str = "0.0.0.0"
    relay_port: int = 8765
    relay_session_timeout_hours: int = 24
    relay_cleanup_interval_seconds: int = 300

    rate_limit_enabled: bool = True
    rate_limit_default_max: int = 120
    rate_limit_default_window_seconds: int = 60
    rate_limit_auth_max: int = 10
    rate_limit_auth_window_seconds: int = 60
    rate_limit_register_max: int = 20
    rate_limit_register_window_seconds: int = 60
    rate_limit_heartbeat_max: int = 60
    rate_limit_heartbeat_window_seconds: int = 60
    rate_limit_websocket_max: int = 30
    rate_limit_websocket_window_seconds: int = 60
    rate_limit_admin_max: int = 60
    rate_limit_admin_window_seconds: int = 60

    stale_device_days: int = 7

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5177",
        "http://localhost:8000",
        "http://localhost:80",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5177",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:80",
    ]

    database_url_sync: str = ""

    def model_post_init(self, _context):
        if not self.encryption_key:
            from cryptography.fernet import Fernet
            self.encryption_key = Fernet.generate_key().decode()
        if not self.database_url_sync:
            self.database_url_sync = self.database_url.replace("+asyncpg", "")
        if self.debug:
            import warnings
            warnings.warn("Debug mode enabled — do not use in production")


settings = Settings()
