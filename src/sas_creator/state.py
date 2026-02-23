import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class RunState:
    completed_steps: dict[str, bool] = field(default_factory=dict)
    step_data: dict[str, Any] = field(default_factory=dict)
    current_step: Optional[str] = None
    attempt_count: dict[str, int] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    _file_path: str = field(default="", repr=False)

    def mark_completed(self, step_name: str, data: dict | None = None) -> None:
        self.completed_steps[step_name] = True
        if data:
            self.step_data[step_name] = data
            self.context.update(data)
        self.save()

    def is_step_completed(self, step_name: str) -> bool:
        return self.completed_steps.get(step_name, False)

    def increment_attempt(self, step_name: str) -> int:
        count = self.attempt_count.get(step_name, 0) + 1
        self.attempt_count[step_name] = count
        self.save()
        return count

    def reset(self) -> None:
        self.completed_steps.clear()
        self.step_data.clear()
        self.current_step = None
        self.attempt_count.clear()
        self.context.clear()
        self.save()

    def save(self) -> None:
        if not self._file_path:
            return
        path = Path(self._file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            k: v for k, v in asdict(self).items() if not k.startswith("_")
        }
        path.write_text(json.dumps(serializable, indent=2))
        logger.debug(f"State saved to {path}")

    @classmethod
    def load(cls, file_path: str) -> "RunState":
        state = cls()
        state._file_path = file_path
        path = Path(file_path)
        if path.exists():
            data = json.loads(path.read_text())
            for key, value in data.items():
                if hasattr(state, key) and not key.startswith("_"):
                    setattr(state, key, value)
            logger.info(
                f"Resumed from state: completed={list(state.completed_steps.keys())}"
            )
        return state
