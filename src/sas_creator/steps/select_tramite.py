import logging

from playwright.sync_api import Page

from sas_creator.config import AppConfig
from sas_creator.steps.base import Step, StepResult, StepStatus
from sas_creator.waiter import wait_for_ajax_settle

logger = logging.getLogger(__name__)


class SelectTramiteStep(Step):
    """After login, either resume a pending process or start a new SAS constitution."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "select_tramite"

    @property
    def display_name(self) -> str:
        return "Select or resume SAS process"

    def check_already_done(self, page: Page) -> bool:
        """If we're past the tramite selection page, this step is done.

        Only returns True if we're on the site AND past the selection page.
        """
        try:
            url = page.url
            if "tuempresa" not in url and "economia.gob" not in url:
                return False
            has_heading = page.locator(
                "text=Iniciar un nuevo trámite"
            ).is_visible(timeout=3000)
            return not has_heading
        except Exception:
            return False

    def execute(self, page: Page, context: dict) -> StepResult:
        cfg = self._config

        # Wait for the page to fully load and confirm key elements are visible
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)
        page.locator("text=Iniciar un nuevo trámite").wait_for(
            state="visible", timeout=cfg.site.page_load_timeout_ms
        )
        self.progress(page, "Tramite selection page loaded", context)

        # Check for pending processes first ("Trámites pendientes" section)
        retomar_link = page.locator("a:has-text('retomar')").first
        try:
            if retomar_link.is_visible(timeout=5000):
                process_info = ""
                try:
                    row = retomar_link.locator("xpath=ancestor::tr")
                    process_info = row.text_content().strip()
                except Exception:
                    pass

                self.progress(page, f"Found pending process. Clicking retomar...", context)
                retomar_link.click()

                # The server can take 6+ minutes to respond (often 504s)
                # Wait for the page to change - either success or error
                try:
                    page.wait_for_load_state(
                        "domcontentloaded", timeout=cfg.site.page_load_timeout_ms
                    )
                except Exception:
                    pass
                wait_for_ajax_settle(
                    page, timeout_ms=cfg.site.ajax_settle_timeout_ms
                )

                # Check if session expired (redirected to login)
                current_url = page.url
                if "login.jsp" in current_url.lower() or "Login" in current_url:
                    return StepResult(
                        status=StepStatus.FAILED,
                        message="Session expired after clicking retomar (redirected to login).",
                    )

                # Check if we got a 504/502 error page
                title = page.title()
                content = page.content()
                if any(code in title + content for code in [
                    "504", "502", "503", "500",
                    "Gateway Time-out", "Bad Gateway", "Server Error",
                ]):
                    return StepResult(
                        status=StepStatus.FAILED,
                        message=f"Server error after clicking retomar: {title}",
                    )

                self.progress(page, "Resumed pending process", context)

                return StepResult(
                    status=StepStatus.SUCCESS,
                    message=f"Resumed pending process. {process_info}",
                    data={"action": "retomar", "process_info": process_info},
                )
        except Exception:
            logger.info("No pending processes found.")

        # No pending process - click "iniciar" next to
        # "Constitución de una Sociedad por Acciones Simplificada"
        self.progress(page, "No pending process. Starting new SAS constitution...", context)

        sas_row = page.locator(
            "tr:has-text('Constitución de una Sociedad por Acciones Simplificada')"
        )
        iniciar_link = sas_row.locator("a:has-text('iniciar')").first

        if not iniciar_link.is_visible(timeout=10000):
            return StepResult(
                status=StepStatus.FAILED,
                message="Could not find 'iniciar' link for SAS constitution.",
            )

        iniciar_link.click()

        try:
            page.wait_for_load_state(
                "domcontentloaded", timeout=cfg.site.page_load_timeout_ms
            )
        except Exception:
            pass
        wait_for_ajax_settle(page, timeout_ms=cfg.site.ajax_settle_timeout_ms)

        # Check if we got a server error page
        title = page.title()
        content = page.content()
        if any(code in title + content for code in [
            "504", "502", "503", "500",
            "Gateway Time-out", "Bad Gateway", "Server Error",
        ]):
            return StepResult(
                status=StepStatus.FAILED,
                message=f"Server error after clicking iniciar: {title}",
            )

        self.progress(page, "Started new SAS constitution process", context)

        return StepResult(
            status=StepStatus.SUCCESS,
            message="Started new SAS constitution process.",
            data={"action": "iniciar"},
        )
