import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramNotifier:
    def __init__(self, config, instance_config=None) -> None:
        self.token = config.token
        self.chat_id = config.chat_id
        self.enabled = bool(self.token and self.chat_id)
        self.instance_name = (
            instance_config.name if instance_config else "default"
        )
        self.novnc_url = (
            instance_config.novnc_base_url if instance_config else ""
        )
        if self.enabled:
            self.base_url = TELEGRAM_API.format(token=self.token)
        else:
            self.base_url = ""
            logger.warning(
                "Telegram notifications disabled (missing token or chat_id)"
            )

    def _prefix_instance(self, message: str) -> str:
        if self.instance_name and self.instance_name != "default":
            return f"[{self.instance_name}] {message}"
        return message

    def send(self, message: str, urgent: bool = False) -> None:
        if not self.enabled:
            logger.info(f"[Telegram disabled] {message}")
            return
        prefix = "\U0001f6a8 " if urgent else "\U0001f916 "
        text = self._prefix_instance(message)
        try:
            resp = httpx.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": f"{prefix}{text}",
                    "parse_mode": "Markdown",
                    "disable_notification": not urgent,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.debug(f"Telegram message sent: {message[:80]}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def send_human_needed(
        self,
        step_name: str,
        message: str,
        screenshot_path: str | None = None,
    ) -> None:
        vnc_link = ""
        if self.novnc_url:
            url = f"{self.novnc_url}/vnc.html?autoconnect=true"
            vnc_link = f"\n\n\U0001f449 [Open Browser]({url})"

        text = (
            f"*HUMAN INTERVENTION NEEDED*\n"
            f"Step: _{step_name}_\n"
            f"{message}{vnc_link}"
        )
        self.send(text, urgent=True)
        if screenshot_path and Path(screenshot_path).exists():
            self._send_photo(
                screenshot_path, caption=f"{self.instance_name}: {step_name}"
            )

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
