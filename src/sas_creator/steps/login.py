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

        Only returns True if we're on the site AND the login form is gone.
        """
        try:
            url = page.url
            if "tuempresa" not in url and "economia.gob" not in url:
                return False
            return not page.locator("input[type='file']").first.is_visible(timeout=3000)
        except Exception:
            return False

    def execute(self, page: Page, context: dict) -> StepResult:
        cfg = self._config

        # 1. Navigate to the login page
        page.goto(
            cfg.site.base_url,
            wait_until="domcontentloaded",
            timeout=cfg.site.navigation_timeout_ms,
        )
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

        # 2. Confirm the login form is fully loaded
        cer_input = page.locator("input[type='file']").first
        cer_input.wait_for(state="attached", timeout=cfg.site.page_load_timeout_ms)
        page.locator("input[type='password']").first.wait_for(
            state="attached", timeout=cfg.site.page_load_timeout_ms
        )
        self.progress(page, "Login page loaded - form elements visible", context)

        # 3. Upload .cer certificate
        cer_input.set_input_files(cfg.credentials.cer_path)
        page.wait_for_timeout(2000)
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        self.progress(page, "Uploaded .cer certificate", context)

        # 3. Read RFC value
        rfc_value = ""
        try:
            rfc_inputs = page.locator("input[readonly], input[disabled]")
            for i in range(rfc_inputs.count()):
                val = rfc_inputs.nth(i).input_value()
                if val and len(val) >= 12:
                    rfc_value = val
                    break
        except Exception:
            logger.warning("Could not read RFC value")

        # 4. Upload .key private key
        file_inputs = page.locator("input[type='file']")
        if file_inputs.count() >= 2:
            file_inputs.nth(1).set_input_files(cfg.credentials.key_path)
        else:
            key_input = page.locator("input[type='file'][accept='.key'], input[type='file']").last
            key_input.set_input_files(cfg.credentials.key_path)
        wait_for_ajax_settle(page, timeout_ms=15000)
        self.progress(page, "Uploaded .key private key", context)

        # 5. Enter password
        pwd_input = page.locator("input[type='password']").first
        pwd_input.wait_for(state="visible", timeout=15000)
        pwd_input.fill(cfg.credentials.password)
        self.progress(page, "Password entered", context)

        # 6. Click "Ingresar" submit button
        submit_btn = page.locator(
            "button:has-text('Ingresar'), "
            "input[type='submit'][value='Ingresar'], "
            "a:has-text('Ingresar'), "
            "button[type='submit']"
        ).first
        submit_btn.click()

        # 7. Wait for login response - the site can take several minutes
        #    Wait for the file inputs to disappear (meaning we left the login page)
        try:
            page.locator("input[type='file']").first.wait_for(
                state="hidden", timeout=cfg.site.page_load_timeout_ms
            )
        except Exception:
            pass  # Timeout - will check below

        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        self.progress(page, "Login submitted, checking result...", context)

        # 8. Verify login success
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
