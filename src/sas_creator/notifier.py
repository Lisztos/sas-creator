import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramNotifier:
    def __init__(self, config) -> None:
        self.token = config.token
        self.chat_id = config.chat_id
        self.enabled = bool(self.token and self.chat_id)
        if self.enabled:
            self.base_url = TELEGRAM_API.format(token=self.token)
        else:
            self.base_url = ""
            logger.warning(
                "Telegram notifications disabled (missing token or chat_id)"
            )

    def send(self, message: str, urgent: bool = False) -> None:
        if not self.enabled:
            logger.info(f"[Telegram disabled] {message}")
            return
        prefix = "\U0001f6a8 " if urgent else "\U0001f916 "
        try:
            resp = httpx.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": f"{prefix}{message}",
                    "parse_mode": "Markdown",
                    "disable_notification": not urgent,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.debug(f"Telegram message sent: {message[:80]}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def send_error(
        self, step_name: str, error: str, screenshot_path: str | None = None
    ) -> None:
        self.send(f"*Step '{step_name}' failed*\n`{error}`", urgent=True)
        if screenshot_path and Path(screenshot_path).exists():
            self._send_photo(screenshot_path, caption=f"Failure at: {step_name}")

    def _send_photo(self, photo_path: str, caption: str = "") -> None:
        if not self.enabled:
            return
        try:
            with open(photo_path, "rb") as f:
                resp = httpx.post(
                    f"{self.base_url}/sendPhoto",
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"photo": f},
                    timeout=30.0,
                )
                resp.raise_for_status()
            logger.debug(f"Telegram photo sent: {photo_path}")
        except Exception as e:
            logger.error(f"Telegram photo send failed: {e}")
