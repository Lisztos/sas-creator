import logging
import random
import time

from sas_creator.browser import BrowserManager
from sas_creator.config import AppConfig
from sas_creator.notifier import TelegramNotifier
from sas_creator.state import RunState
from sas_creator.steps.base import StepResult, StepStatus
from sas_creator.steps.registry import get_step_pipeline
from sas_creator.takeover import TakeoverMonitor

logger = logging.getLogger(__name__)


class StepExecutionError(Exception):
    pass


class Runner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = RunState.load(config.state.state_file)
        self.notifier = TelegramNotifier(config.telegram)
        self.browser_mgr = BrowserManager(config.browser)
        self.steps = get_step_pipeline(config)

    def run(self) -> None:
        page = self.browser_mgr.get_page()
        # Runtime context (not serialized) for steps to access notifier
        self._runtime_context = {
            "_notifier": self.notifier,
            "_screenshot_dir": self.config.state.screenshot_dir,
        }

        # Always start fresh — navigate to login page immediately
        self.state.completed_steps.clear()
        self.state.attempt_count = {}
        self.state.save()

        logger.info("Bot started. Navigating to login page...")
        try:
            page.goto(
                self.config.site.base_url,
                wait_until="commit",
                timeout=self.config.site.navigation_timeout_ms,
            )
        except Exception:
            logger.warning("Initial navigation failed, will retry in login step")
        step_names = [s.name for s in self.steps]
        logger.info("")
        logger.info("=" * 60)
        logger.info("  SAS CREATOR PIPELINE")
        logger.info(f"  Steps: {step_names}")
        logger.info("=" * 60)

        while True:
            restarting = False

            for i, step in enumerate(self.steps, 1):
                # Check for session expiry before non-login steps
                if step.name != "login" and self._is_session_expired(page):
                    logger.info("")
                    logger.warning("--- SESSION EXPIRED - Re-logging in ---")
                    logger.warning("Session expired. Logging in again...")

                    # Clear ALL state — after re-login we must redo every step
                    self.state.completed_steps.clear()
                    self.state.attempt_count.clear()
                    self.state.save()

                    login_step = self.steps[0]
                    login_result = self._execute_step_with_retry(login_step, page)
                    if login_result.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                        self.state.mark_completed("login", login_result.data)
                        logger.info("Re-login successful. Restarting pipeline...")
                        restarting = True
                        break  # break inner for-loop, restart from step 1
                    else:
                        self.notifier.send("Re-login failed.", urgent=True)
                        restarting = False
                        break

                if self.state.is_step_completed(step.name):
                    logger.info(f"  [{i}/{len(self.steps)}] {step.display_name} -- skipped (already done)")
                    continue

                self.state.current_step = step.name
                self.state.save()

                logger.info("")
                logger.info("-" * 60)
                logger.info(f"  STEP {i}/{len(self.steps)}: {step.display_name}")
                logger.info("-" * 60)

                result = self._execute_step_with_retry(step, page)

                # Session expired mid-step — re-login and restart pipeline
                if result.data.get("session_expired"):
                    logger.warning("--- SESSION EXPIRED MID-STEP - Re-logging in ---")
                    self.state.completed_steps.clear()
                    self.state.attempt_count.clear()
                    self.state.save()
                    login_step = self.steps[0]
                    login_result = self._execute_step_with_retry(login_step, page)
                    if login_result.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                        self.state.mark_completed("login", login_result.data)
                        logger.info("Re-login successful. Restarting pipeline...")
                        restarting = True
                        break
                    else:
                        self.notifier.send("Re-login failed.", urgent=True)
                        break

                if result.status == StepStatus.SUCCESS:
                    self.state.mark_completed(step.name, result.data)
                    logger.info(f"  >> OK: {result.message}")
                elif result.status == StepStatus.SKIPPED:
                    self.state.mark_completed(step.name, result.data)
                    logger.info(f"  >> SKIPPED (human take-over)")
                elif result.status == StepStatus.NEEDS_HUMAN:
                    logger.warning(f"  >> NEEDS HUMAN: {result.message}")
                    self.notifier.send(
                        f"HUMAN INTERVENTION NEEDED at step "
                        f"'{step.display_name}': {result.message}",
                        urgent=True,
                    )
                    self._wait_for_human(step, page)
                    self.state.mark_completed(step.name)
                    self.notifier.send(
                        f"Step '{step.display_name}' completed after human intervention."
                    )

            if restarting:
                logger.info("")
                logger.info("=" * 60)
                logger.info("  RESTARTING PIPELINE (after re-login)")
                logger.info("=" * 60)
                continue  # restart the while loop

            break  # all steps done or unrecoverable failure

        logger.info("")
        logger.info("=" * 60)
        logger.info("  PIPELINE COMPLETE")
        logger.info("=" * 60)
        self.notifier.send(
            "All automated steps completed! Browser is open for you to take over. "
            "Press Ctrl+C in the terminal when you're done.",
            urgent=True,
        )
        logger.info("Pipeline complete. Browser stays open. Press Ctrl+C to exit.")

        # Keep the browser alive so the user can take over
        while True:
            time.sleep(60)

    def _execute_step_with_retry(self, step, page) -> StepResult:
        attempt = 0
        cfg = self.config.retry

        while True:
            attempt += 1

            try:
                # Check if human already did this
                if step.check_already_done(page):
                    logger.info(f"Step '{step.name}' already done (human).")
                    return StepResult(
                        status=StepStatus.SKIPPED,
                        message="Human completed this step.",
                    )

                logger.info(f"Executing step '{step.name}' (attempt {attempt})")
                self.state.increment_attempt(step.name)
                ctx = {**self.state.context, **self._runtime_context}
                result = step.execute(page, ctx)

                if result.status in (StepStatus.SUCCESS, StepStatus.NEEDS_HUMAN):
                    return result

                raise StepExecutionError(result.message)

            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    f"  !! FAILED (attempt {attempt}): {error_msg}"
                )

                # Check if we got redirected to the login page (session expired)
                if step.name != "login" and self._is_session_expired(page):
                    logger.warning("  !! Redirected to login page — session expired")
                    return StepResult(
                        status=StepStatus.FAILED,
                        message="Session expired (redirected to login page).",
                        data={"session_expired": True},
                    )

                # Take screenshot
                screenshot_path = step.on_failure(
                    page, e, self.config.state.screenshot_dir
                )

                # Check max attempts
                if 0 < cfg.max_attempts <= attempt:
                    logger.error(
                        f"Max retries ({cfg.max_attempts}) exceeded for '{step.name}'"
                    )
                    return StepResult(
                        status=StepStatus.NEEDS_HUMAN,
                        message=f"Max retries ({cfg.max_attempts}) exceeded: {error_msg}",
                        screenshot_path=screenshot_path,
                    )

                # Server errors (503, 502, etc.) are transient — retry quickly
                is_server_error = any(
                    code in error_msg
                    for code in ["502", "503", "504", "500", "Server error", "Gateway"]
                )

                if is_server_error:
                    delay = 15 + random.uniform(0, 5)
                else:
                    # Normal failures: exponential backoff + jitter
                    delay = min(
                        cfg.base_interval_seconds
                        * (cfg.exponential_base ** (attempt - 1)),
                        cfg.max_interval_seconds,
                    ) + random.uniform(0, cfg.jitter_seconds)

                retry_type = "server error, quick retry" if is_server_error else "backoff"
                logger.info(
                    f"  .. Retrying in {delay:.0f}s ({retry_type}, attempt {attempt + 1})"
                )
                logger.info(
                    f"  Step '{step.display_name}' failed (attempt {attempt}). "
                    f"Retrying in {delay:.0f}s..."
                )

                # Sleep in small increments to allow human take-over detection
                monitor = TakeoverMonitor(page)
                if monitor.wait_for_human_or_timeout(step, delay):
                    return StepResult(
                        status=StepStatus.SKIPPED,
                        message="Human completed this step during retry wait.",
                    )

                # After a server error, reload the page so the next attempt
                # doesn't run against a stale 502/503 error page
                if is_server_error:
                    self._reload_until_ok(page)

                    # Reload may have landed on login (session expired)
                    if step.name != "login" and self._is_session_expired(page):
                        logger.warning("  !! Session expired after reload")
                        return StepResult(
                            status=StepStatus.FAILED,
                            message="Session expired after server error reload.",
                            data={"session_expired": True},
                        )

    def _reload_until_ok(self, page, max_reloads: int = 5) -> None:
        """Reload the page until we get a non-5xx response."""
        for i in range(1, max_reloads + 1):
            logger.info(f"  .. Reloading page before retry (reload {i}/{max_reloads})...")
            try:
                response = page.goto(
                    self.config.site.base_url,
                    wait_until="commit",
                    timeout=self.config.site.navigation_timeout_ms,
                )
                if response and response.status >= 500:
                    logger.warning(f"  .. Reload got {response.status}, retrying in 10s...")
                    page.wait_for_timeout(10000)
                    continue
                logger.info("  .. Reload OK")
                return
            except Exception:
                logger.warning(f"  .. Reload failed (attempt {i}), retrying in 10s...")
                page.wait_for_timeout(10000)
        logger.warning("  .. All reload attempts got errors, proceeding anyway")

    def _is_session_expired(self, page) -> bool:
        """Check if the session expired by looking for the login URL or form."""
        try:
            url = page.url
            if "tuempresa" not in url and "economia.gob" not in url:
                return False
            # Redirect to login page means session expired
            if "login.jsp" in url.lower() or "Login" in url:
                return True
            return page.locator("input[type='file']").first.is_visible(timeout=2000)
        except Exception:
            return False

    def _wait_for_human(self, step, page) -> None:
        """Wait indefinitely for a human to complete the step."""
        logger.info(
            f"Waiting for human to complete step '{step.name}'..."
        )
        monitor = TakeoverMonitor(page, check_interval_seconds=10.0)
        while True:
            if monitor.wait_for_human_or_timeout(step, timeout_seconds=300):
                return
            self.notifier.send(
                f"Still waiting for human at step '{step.display_name}'...",
                urgent=False,
            )
