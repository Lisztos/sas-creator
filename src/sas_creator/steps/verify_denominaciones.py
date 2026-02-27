import logging
import tempfile

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

        Only returns True if we can positively confirm post-verification
        content is visible (content that appears after both Continuar clicks).
        """
        try:
            url = page.url
            if "tuempresa" not in url and "economia.gob" not in url:
                return False
            # Still on one of the Continuar screens — not done
            has_first = page.locator("text=verificaremos que tengas denominaciones disponibles").is_visible(timeout=3000)
            has_second = page.locator("text=disponibles").is_visible(timeout=2000)
            if has_first or has_second:
                return False
            # Positive signal: form/content that appears after the verification screens
            # The next stage typically has form fields for the SAS constitution
            has_form = page.locator("input[type='text'], textarea, select").first.is_visible(timeout=2000)
            return has_form
        except Exception:
            return False

    def _wait_for_processing_modal(self, page: Page) -> None:
        """Wait for the 'Procesando...' modal to appear and disappear."""
        cfg = self._config
        modal_selectors = [
            "text=Verificando denominaciones",
            "text=Procesando",
            ".modal:has-text('Verificando')",
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

    def _check_for_errors(self, page: Page, server_errors: list[tuple[int, str]] | None = None) -> str | None:
        """Check for server errors or session expiry. Returns error message or None."""
        url = page.url
        if "login.jsp" in url.lower() or "Login" in url:
            return "Session expired (redirected to login)."

        # Check actual HTTP 5xx responses captured during the action
        if server_errors:
            status_code, err_url = server_errors[0]
            return f"Server error {status_code}"
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

        for attempt in range(1, max_retries + 1):
            continuar_btn = page.locator(
                "button:has-text('Continuar'), a:has-text('Continuar')"
            ).first
            if not continuar_btn.is_visible(timeout=10000):
                return f"Could not find '{label}' Continuar button."

            logger.info(f"Clicking '{label}' Continuar (attempt {attempt})...")
            with self.capture_server_errors(page) as server_errors:
                continuar_btn.click()
                self._wait_for_processing_modal(page)

            error = self._check_for_errors(page, server_errors)
            if error:
                return f"After {label} Continuar: {error}"

            # Check if we actually advanced past this screen
            body_text = page.locator("body").inner_text().lower()
            if screen_marker not in body_text:
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
        # The text is rendered by JS after the first Continuar completes.
        # Check page text directly with Python (more robust than Playwright's
        # text= locator, which fails when words span multiple HTML elements).
        # NOTE: the site has a typo — "denonimaciones" instead of "denominaciones"
        second_marker = "disponibles"
        found_second = False

        for poll in range(1, 6):
            wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

            # Fail fast on browser-level errors (connection timeout, etc.)
            browser_err = self.is_browser_error(page)
            if browser_err:
                return StepResult(
                    status=StepStatus.FAILED,
                    message=f"Browser error on second Continuar screen: {browser_err}",
                )

            body_text = page.locator("body").inner_text()
            if second_marker in body_text.lower():
                found_second = True
                break
            logger.info(f"Second screen poll {poll}/5 - not found yet. Page text: {body_text[:300]!r}")
            page.wait_for_timeout(5000)

        if found_second:
            self.progress(page, "Second Continuar screen visible - denominaciones confirmed!", context)

            error = self._click_continuar_until_advanced(page, second_marker, "second")
            if error:
                return StepResult(status=StepStatus.FAILED, message=error)

            self.progress(page, "Second Continuar completed", context)
        else:
            # Dump HTML so we can see what the page actually shows
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", prefix="second_screen_missing_", delete=False
            ) as f:
                f.write(page.content())
                logger.warning(f"Second screen HTML dumped to {f.name}")

            return StepResult(
                status=StepStatus.FAILED,
                message="Second Continuar screen not found after 5 poll attempts.",
            )

        # Dump page source so we can inspect the next (unknown) screen
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", prefix="next_screen_", delete=False
        ) as f:
            f.write(page.content())
            logger.info(f"Next screen HTML saved to {f.name}")

        return StepResult(
            status=StepStatus.SUCCESS,
            message="Denominaciones verified. Both Continuar screens completed.",
            data={"action": "denominaciones_verified"},
        )
