import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from playwright.sync_api import Page

if TYPE_CHECKING:
    from sas_creator.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

PROGRESS_PAUSE_SECONDS = 3


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_HUMAN = "needs_human"


@dataclass
class StepResult:
    status: StepStatus
    message: str = ""
    screenshot_path: Optional[str] = None
    data: dict = field(default_factory=dict)


class Step(ABC):
    """Abstract base class for all automation steps."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this step."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for notifications."""
        ...

    @abstractmethod
    def check_already_done(self, page: Page) -> bool:
        """Return True if this step was already completed (e.g. by a human)."""
        ...

    @abstractmethod
    def execute(self, page: Page, context: dict) -> StepResult:
        """Perform the step's actions. Returns a StepResult."""
        ...

    def progress(self, page: Page, message: str, context: dict) -> None:
        """Log progress and pause so the user can see the browser."""
        logger.info(f"[{self.name}] {message}")
        page.wait_for_timeout(PROGRESS_PAUSE_SECONDS * 1000)

    def on_failure(self, page: Page, error: Exception, screenshot_dir: str = "./screenshots") -> Optional[str]:
        """Take a screenshot on failure. Returns path to screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(Path(screenshot_dir) / f"{self.name}_{timestamp}.png")
        try:
            Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=path, full_page=True)
            return path
        except Exception:
            return None
