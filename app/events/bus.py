import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = {}

    def register(self, event_type: type, handler: Callable) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Any) -> None:
        handlers = self._handlers.get(type(event), [])
        if not handlers:
            logger.warning(f"No handlers registered for {type(event).__name__}")
            return
        for handler in handlers:
            handler(event)


event_bus = EventBus()
