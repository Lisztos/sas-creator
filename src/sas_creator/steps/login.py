import logging

from playwright.sync_api import Page

from sas_creator.config import AppConfig
from sas_creator.steps.base import Step, StepResult, StepStatus
from sas_creator.waiter import wait_for_ajax_settle

logger = logging.getLogger(__name__)


class LoginStep(Step):
    """Log in to tuempresa.gob.mx using e.firma (.cer + .key + password)."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "login"

    @property
    def display_name(self) -> str:
        return "Login with e.firma"

    def check_already_done(self, page: Page) -> bool:
        """Check if we're already past the login page.

        If the login form is gone, we're already logged in.
        """
        try:
            # The login page has file inputs for .cer/.key - if those are absent,
            # we've moved past login
            return not page.locator("input[type='file']").first.is_visible(timeout=3000)
        except Exception:
            return False

    def execute(self, page: Page, context: dict) -> StepResult:
        cfg = self._config

        # 1. Navigate to the login page
        logger.info(f"Navigating to {cfg.site.base_url}")
        page.goto(
            cfg.site.base_url,
            wait_until="domcontentloaded",
            timeout=cfg.site.navigation_timeout_ms,
        )

        # 2. Wait for AJAX framework to initialize
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

        # 3. Upload .cer certificate
        logger.info("Uploading .cer certificate...")
        cer_input = page.locator("input[type='file']").first
        cer_input.wait_for(state="attached", timeout=30000)
        cer_input.set_input_files(cfg.credentials.cer_path)

        # 4. Wait for RFC to auto-populate after .cer upload
        logger.info("Waiting for RFC to auto-populate...")
        page.wait_for_timeout(2000)  # Brief pause for AJAX
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

        # Try to read the RFC value
        rfc_value = ""
        try:
            rfc_inputs = page.locator("input[readonly], input[disabled]")
            for i in range(rfc_inputs.count()):
                val = rfc_inputs.nth(i).input_value()
                if val and len(val) >= 12:  # RFC is 12-13 chars
                    rfc_value = val
                    break
        except Exception:
            logger.warning("Could not read RFC value")

        # 5. Upload .key private key
        logger.info("Uploading .key private key...")
        file_inputs = page.locator("input[type='file']")
        # The second file input is for the .key
        if file_inputs.count() >= 2:
            file_inputs.nth(1).set_input_files(cfg.credentials.key_path)
        else:
            # Fallback: find by accept attribute or nearby label
            key_input = page.locator("input[type='file'][accept='.key'], input[type='file']").last
            key_input.set_input_files(cfg.credentials.key_path)

        wait_for_ajax_settle(page, timeout_ms=15000)

        # 6. Enter password
        logger.info("Entering password...")
        pwd_input = page.locator("input[type='password']").first
        pwd_input.wait_for(state="visible", timeout=15000)
        pwd_input.fill(cfg.credentials.password)

        # 7. Click "Ingresar" submit button
        logger.info("Clicking Ingresar...")
        submit_btn = page.locator(
            "button:has-text('Ingresar'), "
            "input[type='submit'][value='Ingresar'], "
            "a:has-text('Ingresar'), "
            "button[type='submit']"
        ).first
        submit_btn.click()

        # 8. Wait for navigation/AJAX response
        logger.info("Waiting for login response...")
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        page.wait_for_timeout(3000)  # Extra buffer for slow site

        # 9. Verify login success
        if self.check_already_done(page):
            logger.info(f"Login successful! RFC: {rfc_value}")
            return StepResult(
                status=StepStatus.SUCCESS,
                message=f"Logged in successfully. RFC: {rfc_value}",
                data={"rfc": rfc_value},
            )

        # Check for error messages
        error_selectors = [
            ".alert-danger",
            ".error-message",
            ".wr-error",
            ".alert-warning",
            "[class*='error']",
            "[class*='Error']",
        ]
        for selector in error_selectors:
            try:
                el = page.locator(selector)
                if el.is_visible(timeout=1000):
                    error_text = el.text_content()
                    return StepResult(
                        status=StepStatus.FAILED,
                        message=f"Login failed. Site error: {error_text}",
                    )
            except Exception:
                continue

        # Check if we got a server error page (502, 503, etc.)
        title = page.title()
        if any(code in title for code in ["502", "503", "500", "Error"]):
            return StepResult(
                status=StepStatus.FAILED,
                message=f"Server error page: {title}",
            )

        return StepResult(
            status=StepStatus.FAILED,
            message="Login did not succeed. No post-login content detected.",
        )
