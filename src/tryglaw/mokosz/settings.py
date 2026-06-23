from pydantic_settings import BaseSettings, SettingsConfigDict


class MokoszSettings(BaseSettings):
    perun_ws_url: str = "ws://localhost:19000/ws"
    api_key: str = ""
    description: str = "Mokosz Instance"
    system: str = ""
    environment: str = ""
    target_timeout: float = 300.0
    log_level: str = "DEBUG"
    payload_log_file: str = ""
    tls_verify: bool = True

    model_config = SettingsConfigDict(
        env_prefix="MOKOSZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
