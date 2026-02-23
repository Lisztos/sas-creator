import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator


class SiteConfig(BaseModel):
    base_url: str
    page_load_timeout_ms: int = 120000
    ajax_settle_timeout_ms: int = 30000
    navigation_timeout_ms: int = 120000


class CredentialsConfig(BaseModel):
    cer_path: str
    key_path: str
    password: str = ""

    @field_validator("cer_path", "key_path")
    @classmethod
    def validate_file_exists(cls, v: str) -> str:
        p = Path(v)
        if not p.exists():
            raise ValueError(f"File not found: {p.resolve()}")
        return str(p.resolve())


class RetryConfig(BaseModel):
    base_interval_seconds: int = 300
    max_interval_seconds: int = 1800
    exponential_base: int = 2
    jitter_seconds: int = 30
    max_attempts: int = 0


class TelegramConfig(BaseModel):
    token: str = ""
    chat_id: str = ""
    notify_on_step_success: bool = True
    notify_on_error: bool = True
    notify_on_human_needed: bool = True
    send_screenshots: bool = True


class BrowserConfig(BaseModel):
    headless: bool = False
    slow_mo_ms: int = 100
    viewport_width: int = 1280
    viewport_height: int = 900
    user_data_dir: str = "./browser_data"


class StateConfig(BaseModel):
    state_file: str = "./state/run_state.json"
    screenshot_dir: str = "./screenshots"


class LoggingConfig(BaseModel):
    level: str = "DEBUG"
    file: str = "./logs/sas_creator.log"
    max_bytes: int = 10485760
    backup_count: int = 5


class AppConfig(BaseModel):
    site: SiteConfig
    credentials: CredentialsConfig
    retry: RetryConfig = RetryConfig()
    telegram: TelegramConfig = TelegramConfig()
    browser: BrowserConfig = BrowserConfig()
    state: StateConfig = StateConfig()
    logging: LoggingConfig = LoggingConfig()


def load_config(config_path: str = "config.yaml") -> AppConfig:
    load_dotenv()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Inject secrets from environment
    if "credentials" not in raw:
        raw["credentials"] = {}
    raw["credentials"]["password"] = os.environ.get("SAS_KEY_PASSWORD", "")

    if "telegram" not in raw:
        raw["telegram"] = {}
    raw["telegram"]["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    return AppConfig(**raw)
