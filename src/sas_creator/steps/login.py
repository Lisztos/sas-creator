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

        Only returns True if we can positively confirm post-login content
        is visible (e.g. the tramite selection page).
        """
        try:
            url = page.url
            if "tuempresa" not in url and "economia.gob" not in url:
                return False
            # Positive signal: post-login content is visible
            has_tramite = page.locator("text=Iniciar un nuevo trámite").is_visible(timeout=3000)
            has_retomar = page.locator("a:has-text('retomar')").first.is_visible(timeout=1000)
            return has_tramite or has_retomar
        except Exception:
            return False

    def execute(self, page: Page, context: dict) -> StepResult:
        cfg = self._config

        # 1. Navigate to the login page
        response = page.goto(
            cfg.site.base_url,
            wait_until="commit",
            timeout=cfg.site.navigation_timeout_ms,
        )

        # Check HTTP status directly — fail fast on server errors
        if response and response.status >= 500:
            return StepResult(
                status=StepStatus.FAILED,
                message=f"Server error {response.status} on login page",
            )

        # Check for server error page BEFORE ajax settle (which can wait 2+ min)
        title = page.title()
        if any(code in title for code in ["502", "503", "500", "504", "Error", "Gateway"]):
            return StepResult(
                status=StepStatus.FAILED,
                message=f"Server error on login page: {title}",
            )

        # Page is OK — wait for DOM to be ready before interacting
        page.wait_for_load_state("domcontentloaded", timeout=cfg.site.navigation_timeout_ms)
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

        # 2. Confirm the login form is fully loaded
        cer_input = page.locator("input[type='file']").first
        cer_input.wait_for(state="attached", timeout=cfg.site.page_load_timeout_ms)
        page.locator("input[type='password']").first.wait_for(
            state="attached", timeout=cfg.site.page_load_timeout_ms
        )
        self.progress(page, "Login page loaded - form elements visible", context)

        # 3. Upload .cer certificate via file chooser
        with page.expect_file_chooser() as fc_info:
            cer_input.click()
        fc_info.value.set_files(cfg.credentials.cer_path)
        page.wait_for_timeout(3000)
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        self.progress(page, "Uploaded .cer certificate", context)

        # 4. Read RFC value (confirms the site actually processed the .cer)
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

        if rfc_value:
            logger.info(f"RFC populated: {rfc_value} - certificate was processed")
        else:
            logger.warning("RFC not populated - site may not have processed the .cer file")

        # 5. Upload .key private key via file chooser
        file_inputs = page.locator("input[type='file']")
        if file_inputs.count() >= 2:
            key_input = file_inputs.nth(1)
        else:
            key_input = page.locator("input[type='file'][accept='.key'], input[type='file']").last
        with page.expect_file_chooser() as fc_info:
            key_input.click()
        fc_info.value.set_files(cfg.credentials.key_path)
        page.wait_for_timeout(2000)
        wait_for_ajax_settle(page, timeout_ms=15000)
        self.progress(page, "Uploaded .key private key", context)

        # 5. Enter password
        pwd_input = page.locator("input[type='password']").first
        pwd_input.wait_for(state="visible", timeout=15000)
        pwd_input.fill(cfg.credentials.password)
        # Click outside to trigger blur/change, then wait before submitting
        page.locator("body").click(position={"x": 0, "y": 0})
        page.wait_for_timeout(1000)
        self.progress(page, "Password entered", context)

        # 6. Intercept $.notify() calls and console errors before submitting.
        #    The site uses $.notify() to show validation messages, but the plugin
        #    sometimes fails to load ("$.notify is not a function").  We patch it
        #    so the message is captured even when the plugin is broken.
        page.evaluate("""() => {
            window.__capturedNotifications = [];
            window.__consoleErrors = [];

            // Patch $.notify if jQuery is available
            if (window.jQuery) {
                jQuery.notify = function(msg, opts) {
                    var text = (typeof msg === 'string') ? msg : JSON.stringify(msg);
                    var type = (opts && opts.type) ? opts.type : 'unknown';
                    window.__capturedNotifications.push({text: text, type: type});
                    console.warn('[intercepted $.notify] ' + type + ': ' + text);
                };
                jQuery.fn.notify = jQuery.notify;
            }

            // Capture console.error calls
            var _origError = console.error;
            console.error = function() {
                var msg = Array.prototype.slice.call(arguments).join(' ');
                window.__consoleErrors.push(msg);
                _origError.apply(console, arguments);
            };
        }""")
        self.progress(page, "Notification interceptor installed", context)

        # 7. Click "Ingresar" submit button
        page.wait_for_timeout(1000)  # Let the page settle before clicking

        submit_btn = page.locator(
            "button:has-text('Ingresar'), "
            "input[type='submit'][value='Ingresar'], "
            "a:has-text('Ingresar'), "
            "button[type='submit']"
        ).first

        # Log details about the button before clicking
        btn_tag = submit_btn.evaluate("el => el.tagName")
        btn_text = submit_btn.text_content()
        btn_enabled = submit_btn.is_enabled()
        btn_visible = submit_btn.is_visible()
        logger.info(
            f"Ingresar button: tag={btn_tag}, text='{btn_text}', "
            f"enabled={btn_enabled}, visible={btn_visible}"
        )

        submit_btn.click()
        logger.info("Ingresar button clicked!")

        # 8. Wait for login response - the site can take several minutes
        #    Wait for the file inputs to disappear (meaning we left the login page)
        try:
            page.locator("input[type='file']").first.wait_for(
                state="hidden", timeout=cfg.site.page_load_timeout_ms
            )
        except Exception:
            pass  # Timeout - will check below

        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        self.progress(page, "Login submitted, checking result...", context)

        # 9. Read intercepted notifications and console errors
        intercepted = page.evaluate("""() => ({
            notifications: window.__capturedNotifications || [],
            errors: window.__consoleErrors || [],
        })""")

        captured_msgs = intercepted.get("notifications", [])
        console_errors = intercepted.get("errors", [])

        if captured_msgs:
            msgs_text = "; ".join(n["text"] for n in captured_msgs)
            logger.warning(f"Intercepted site notifications: {msgs_text}")
        if console_errors:
            logger.warning(f"Console errors: {'; '.join(console_errors[:5])}")

        # 10. Verify login success
        if self.check_already_done(page):
            logger.info(f"Login successful! RFC: {rfc_value}")
            return StepResult(
                status=StepStatus.SUCCESS,
                message=f"Logged in successfully. RFC: {rfc_value}",
                data={"rfc": rfc_value},
            )

        # Build failure detail from intercepted messages
        failure_detail = ""
        if captured_msgs:
            failure_detail = "Site message: " + "; ".join(
                n["text"] for n in captured_msgs
            )

        # Check for error messages in the DOM
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
                        message=f"Login failed. DOM error: {error_text}. {failure_detail}",
                    )
            except Exception:
                continue

        # Check if we got a server error page (502, 503, etc.)
        title = page.title()
        if any(code in title for code in ["502", "503", "500", "Error"]):
            return StepResult(
                status=StepStatus.FAILED,
                message=f"Server error page: {title}. {failure_detail}",
            )

        # If we captured notifications, report them even if no DOM error found
        if failure_detail:
            return StepResult(
                status=StepStatus.FAILED,
                message=f"Login did not succeed. {failure_detail}",
            )

        return StepResult(
            status=StepStatus.FAILED,
            message="Login did not succeed. No post-login content or error detected.",
        )
