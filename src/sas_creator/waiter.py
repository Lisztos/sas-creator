import logging

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def wait_for_ajax_settle(page: Page, timeout_ms: int = 30000) -> None:
    """Wait for WebRatio AJAX operations to complete using a multi-layer strategy."""

    # Layer 1: Wait for network idle (no requests for 500ms)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        logger.warning("Network idle timeout - proceeding with DOM checks.")

    # Layer 2: Wait for jQuery AJAX to complete (if jQuery is present)
    try:
        page.wait_for_function(
            """() => {
                if (typeof jQuery !== 'undefined') {
                    return jQuery.active === 0;
                }
                return true;
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        logger.warning("jQuery.active check timeout - proceeding.")

    # Layer 3: Wait for WebRatio-specific loading indicators to disappear
    try:
        loading = page.locator(".wr-loading, .loading-overlay, .ajax-loading")
        if loading.count() > 0:
            loading.first.wait_for(state="hidden", timeout=timeout_ms)
    except Exception:
        pass

    # Layer 4: Wait for DOM to stabilize (no mutations for 1s)
    try:
        page.wait_for_function(
            """() => {
                return new Promise(resolve => {
                    const target = document.querySelector('.wr-ajaxDiv') || document.body;
                    let timer = null;
                    const observer = new MutationObserver(() => {
                        clearTimeout(timer);
                        timer = setTimeout(() => {
                            observer.disconnect();
                            resolve(true);
                        }, 1000);
                    });
                    observer.observe(target, {
                        childList: true, subtree: true, attributes: true
                    });
                    timer = setTimeout(() => {
                        observer.disconnect();
                        resolve(true);
                    }, 2000);
                });
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        logger.warning("DOM stability check timeout - proceeding.")


def wait_for_element_value(
    page: Page, selector: str, timeout_ms: int = 30000
) -> None:
    """Wait until a form field has a non-empty value."""
    page.wait_for_function(
        f"() => document.querySelector('{selector}')?.value?.trim().length > 0",
        timeout=timeout_ms,
    )
