import logging

from playwright.sync_api import Page

from sas_creator.config import AppConfig
from sas_creator.steps.base import Step, StepResult, StepStatus
from sas_creator.waiter import wait_for_ajax_settle

logger = logging.getLogger(__name__)


class VerifyDenominacionesStep(Step):
    """Click through the two 'Continuar' screens that verify available denominaciones."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "verify_denominaciones"

    @property
    def display_name(self) -> str:
        return "Verify denominaciones disponibles"

    def check_already_done(self, page: Page) -> bool:
        """If we're past both Continuar screens, this step is done.

        Returns False on error pages (503, etc.) so they get retried.
        """
        try:
            url = page.url
            if "tuempresa" not in url and "economia.gob" not in url:
                return False
            # Don't consider error pages as "done"
            title = page.title()
            if any(code in title for code in ["502", "503", "504", "500", "Error", "Gateway"]):
                return False
            # If neither of the two known messages is visible, we've moved past them
            has_first = page.locator("text=verificaremos que tengas denominaciones disponibles").is_visible(timeout=3000)
            has_second = page.locator("text=tienes denominaciones disponibles").is_visible(timeout=2000)
            if has_first or has_second:
                return False
            return True
        except Exception:
            return False

    def _wait_for_processing_modal(self, page: Page) -> None:
        """Wait for the 'Procesando...' modal to appear and disappear."""
        cfg = self._config
        modal_selectors = [
            "text=Procesando",
            ".modal:has-text('Procesando')",
            ".modal-backdrop",
        ]

        # Wait for modal to appear
        modal_appeared = False
        for selector in modal_selectors:
            try:
                if page.locator(selector).first.is_visible(timeout=5000):
                    modal_appeared = True
                    logger.info(f"Processing modal detected ({selector})")
                    break
            except Exception:
                continue

        if not modal_appeared:
            logger.info("No processing modal detected, waiting for page to settle...")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=cfg.site.page_load_timeout_ms)
            except Exception:
                pass
            wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
            return

        # Wait for modal to disappear
        logger.info("Waiting for processing modal to disappear...")
        for selector in modal_selectors:
            try:
                page.locator(selector).first.wait_for(
                    state="hidden", timeout=cfg.site.page_load_timeout_ms
                )
            except Exception:
                pass

        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        logger.info("Processing modal gone.")

    def _check_for_errors(self, page: Page) -> str | None:
        """Check for server errors or session expiry. Returns error message or None."""
        url = page.url
        if "login.jsp" in url.lower() or "Login" in url:
            return "Session expired (redirected to login)."

        title = page.title()
        content = page.content()
        for code in ["504", "502", "503", "500", "Gateway Time-out", "Bad Gateway", "Server Error"]:
            if code in title or code in content:
                return f"Server error: {title}"
        return None

    def _click_continuar_until_advanced(
        self, page: Page, screen_marker: str, label: str, max_retries: int = 10
    ) -> str | None:
        """Click 'Continuar' repeatedly until the current screen changes.

        The 'Procesando...' modal may disappear without the page advancing.
        We detect this by checking if `screen_marker` text is still visible
        and clicking again.

        Returns an error message string, or None on success.
        """
        cfg = self._config
        marker_locator = page.locator(f"text={screen_marker}")

        for attempt in range(1, max_retries + 1):
            continuar_btn = page.locator(
                "button:has-text('Continuar'), a:has-text('Continuar')"
            ).first
            if not continuar_btn.is_visible(timeout=10000):
                return f"Could not find '{label}' Continuar button."

            logger.info(f"Clicking '{label}' Continuar (attempt {attempt})...")
            continuar_btn.click()
            self._wait_for_processing_modal(page)

            error = self._check_for_errors(page)
            if error:
                return f"After {label} Continuar: {error}"

            # Check if we actually advanced past this screen
            if not marker_locator.is_visible(timeout=3000):
                logger.info(f"'{label}' screen is gone - advanced successfully.")
                return None

            logger.warning(
                f"'{label}' screen still visible after attempt {attempt}. "
                f"Modal disappeared but page didn't advance. Retrying..."
            )
            page.wait_for_timeout(2000)

        return f"'{label}' Continuar did not advance after {max_retries} attempts."

    def execute(self, page: Page, context: dict) -> StepResult:
        cfg = self._config

        # --- First Continuar: "verificaremos que tengas denominaciones disponibles" ---
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

        first_marker = "verificaremos que tengas denominaciones disponibles"
        first_msg = page.locator(f"text={first_marker}")
        try:
            first_msg.wait_for(state="visible", timeout=cfg.site.page_load_timeout_ms)
        except Exception:
            pass

        if first_msg.is_visible(timeout=3000):
            self.progress(page, "First Continuar screen visible", context)

            error = self._click_continuar_until_advanced(page, first_marker, "first")
            if error:
                return StepResult(status=StepStatus.FAILED, message=error)

            self.progress(page, "First Continuar completed", context)

        # --- Second Continuar: "tienes denominaciones disponibles" ---
        second_marker = "tienes denominaciones disponibles"
        second_msg = page.locator(f"text={second_marker}")
        try:
            second_msg.wait_for(state="visible", timeout=cfg.site.page_load_timeout_ms)
        except Exception:
            pass

        if second_msg.is_visible(timeout=3000):
            self.progress(page, "Second Continuar screen visible - denominaciones confirmed!", context)

            error = self._click_continuar_until_advanced(page, second_marker, "second")
            if error:
                return StepResult(status=StepStatus.FAILED, message=error)

            self.progress(page, "Second Continuar completed", context)
        else:
            logger.warning("Second Continuar screen not found - may have been skipped")

        return StepResult(
            status=StepStatus.SUCCESS,
            message="Denominaciones verified. Both Continuar screens completed.",
            data={"action": "denominaciones_verified"},
        )
