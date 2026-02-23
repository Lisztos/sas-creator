import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sas_creator.config import load_config
from sas_creator.runner import Runner


def setup_logging(log_config) -> None:
    Path(log_config.file).parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_config.file,
        maxBytes=log_config.max_bytes,
        backupCount=log_config.backup_count,
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_config.level.upper()))
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stdout))


def main() -> None:
    config = load_config()
    setup_logging(config.logging)

    logger = logging.getLogger(__name__)
    logger.info("SAS Creator bot starting...")

    runner = Runner(config)
    try:
        runner.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user. State has been saved.")
        runner.notifier.send("Bot stopped by user (Ctrl+C).")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        runner.notifier.send(f"Bot crashed: {e}", urgent=True)
        sys.exit(1)
    finally:
        runner.browser_mgr.close()


if __name__ == "__main__":
    main()
