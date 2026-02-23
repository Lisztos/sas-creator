import logging

from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self, config) -> None:
        self.config = config
        self._playwright = None
        self._context = None
        self._page: Page | None = None

    def get_page(self) -> Page:
        if self._page and not self._page.is_closed():
            return self._page

        self._playwright = sync_playwright().start()

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.config.user_data_dir,
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            locale="es-MX",
            timezone_id="America/Mexico_City",
        )

        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()

        self._page.set_default_timeout(120000)
        self._page.set_default_navigation_timeout(120000)

        logger.info("Browser launched in headed mode with persistent context.")
        return self._page

    def take_screenshot(self, path: str) -> None:
        if self._page and not self._page.is_closed():
            self._page.screenshot(path=path, full_page=True)

    def close(self) -> None:
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        logger.info("Browser closed.")
