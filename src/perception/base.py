"""Abstract base class for platform-specific perception implementations."""

from abc import ABC, abstractmethod
from .snapshot import PerceptionSnapshot


class AbstractPerception(ABC):
    """Interface for platform-specific desktop perception."""

    @abstractmethod
    def get_snapshot(self) -> PerceptionSnapshot:
        """Capture current desktop context."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this implementation is available on the current platform."""
        ...