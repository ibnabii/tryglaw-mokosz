from pydantic_settings import BaseSettings, SettingsConfigDict

from tryglaw.common.security import parse_key_list


class MokoszSettings(BaseSettings):
    perun_ws_url: str = "ws://localhost:19000/ws"
    api_key: str = ""
    description: str = "Mokosz Instance"
    target_timeout: float = 300.0
    log_level: str = "DEBUG"
    payload_log_file: str = ""
    tls_verify: bool = True
    access_keys: str = ""
    allow_proxy: bool = False
    fileshare_enabled: bool = False
    fileshare_config: str = ""

    @property
    def access_keys_list(self) -> list[str]:
        return parse_key_list(self.access_keys)

    model_config = SettingsConfigDict(
        env_prefix="MOKOSZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
