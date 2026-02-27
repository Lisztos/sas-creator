import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from sas_creator.config import load_config
from sas_creator.runner import Runner


def setup_logging(log_config) -> None:
    Path(log_config.file).parent.mkdir(parents=True, exist_ok=True)

    # File handler — full detail for debugging
    file_handler = RotatingFileHandler(
        log_config.file,
        maxBytes=log_config.max_bytes,
        backupCount=log_config.backup_count,
    )
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    # Console handler — Rich for clean, colored output
    console = RichHandler(
        rich_tracebacks=True,
        show_path=False,
        markup=True,
    )

    # Suppress noisy HTTP/connection logs on console
    console.addFilter(lambda record: "httpcore" not in record.name)
    console.addFilter(lambda record: "httpx" not in record.name)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_config.level.upper()))
    root.addHandler(file_handler)
    root.addHandler(console)


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
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        try:
            runner.browser_mgr.close()
        except (KeyboardInterrupt, Exception):
            pass


if __name__ == "__main__":
    main()
