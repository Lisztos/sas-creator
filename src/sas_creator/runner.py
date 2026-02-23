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
        self.notifier.send("Bot started. Beginning automation pipeline.")
        logger.info(
            f"Pipeline has {len(self.steps)} steps: "
            f"{[s.name for s in self.steps]}"
        )

        for step in self.steps:
            if self.state.is_step_completed(step.name):
                logger.info(f"Step '{step.name}' already completed. Skipping.")
                continue

            self.state.current_step = step.name
            self.state.save()

            result = self._execute_step_with_retry(step, page)

            if result.status == StepStatus.SUCCESS:
                self.state.mark_completed(step.name, result.data)
                self.notifier.send(
                    f"Step '{step.display_name}' completed!\n{result.message}"
                )
            elif result.status == StepStatus.SKIPPED:
                self.state.mark_completed(step.name, result.data)
                self.notifier.send(
                    f"Step '{step.display_name}' was already done (human take-over)."
                )
            elif result.status == StepStatus.NEEDS_HUMAN:
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

        self.notifier.send("All steps completed successfully!")
        logger.info("Pipeline complete.")

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
                result = step.execute(page, self.state.context)

                if result.status in (StepStatus.SUCCESS, StepStatus.NEEDS_HUMAN):
                    return result

                raise StepExecutionError(result.message)

            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    f"Step '{step.name}' failed (attempt {attempt}): {error_msg}"
                )

                # Take screenshot
                screenshot_path = step.on_failure(
                    page, e, self.config.state.screenshot_dir
                )

                # Notify
                self.notifier.send_error(step.display_name, error_msg, screenshot_path)

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

                # Calculate delay with exponential backoff + jitter
                delay = min(
                    cfg.base_interval_seconds
                    * (cfg.exponential_base ** (attempt - 1)),
                    cfg.max_interval_seconds,
                ) + random.uniform(0, cfg.jitter_seconds)

                logger.info(
                    f"Retrying step '{step.name}' in {delay:.0f}s "
                    f"(attempt {attempt + 1})"
                )
                self.notifier.send(
                    f"Step '{step.display_name}' failed (attempt {attempt}). "
                    f"Retrying in {delay:.0f}s..."
                )

                # Sleep in small increments to allow human take-over detection
                monitor = TakeoverMonitor(page)
                if monitor.wait_for_human_or_timeout(step, delay):
                    return StepResult(
                        status=StepStatus.SKIPPED,
                        message="Human completed this step during retry wait.",
                    )

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
