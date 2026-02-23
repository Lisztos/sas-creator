import logging
import time

from playwright.sync_api import Page

from sas_creator.steps.base import Step

logger = logging.getLogger(__name__)


class TakeoverMonitor:
    """Monitors the page for human-driven progress.

    During retry wait periods, periodically checks if the human
    has completed the current step manually.
    """

    def __init__(self, page: Page, check_interval_seconds: float = 5.0) -> None:
        self.page = page
        self.check_interval = check_interval_seconds

    def wait_for_human_or_timeout(
        self, step: Step, timeout_seconds: float
    ) -> bool:
        """Block until either:
        1. The step's check_already_done() returns True (human finished it), or
        2. The timeout expires.

        Returns True if the human completed the step.
        """
        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                if step.check_already_done(self.page):
                    logger.info(f"Human completed step '{step.name}'.")
                    return True
            except Exception:
                pass  # Page may be navigating
            time.sleep(self.check_interval)
        return False

    def snapshot_url(self) -> str:
        return self.page.url

    def has_url_changed(self, previous_url: str) -> bool:
        try:
            return self.page.url != previous_url
        except Exception:
            return False
