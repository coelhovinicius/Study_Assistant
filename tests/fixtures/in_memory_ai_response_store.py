"""Dublês do que a análise em lotes usa pra guardar respostas e esperar
entre chamadas — sem Turso e sem esperar de verdade."""

from __future__ import annotations

from study_assistant.domain.entities import SavedAIResponse
from study_assistant.domain.exceptions import RepositoryError
from study_assistant.domain.ports import AIResponseStore


class InMemoryAIResponseStore(AIResponseStore):
    def __init__(self, *, broken: bool = False) -> None:
        self.saved: dict[str, SavedAIResponse] = {}
        self.purged_days: list[int] = []
        self._broken = broken

    def get(self, key: str) -> SavedAIResponse | None:
        if self._broken:
            raise RepositoryError("turso fora do ar")
        return self.saved.get(key)

    def save(self, key: str, response: SavedAIResponse) -> None:
        if self._broken:
            raise RepositoryError("turso fora do ar")
        self.saved[key] = response

    def purge_older_than(self, days: int) -> None:
        if self._broken:
            raise RepositoryError("turso fora do ar")
        self.purged_days.append(days)


class FakeClock:
    """Relógio que só anda quando alguém "dorme" — ``sleep`` registra cada
    espera, pra conferir quanto o app esperou sem esperar de verdade."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    @property
    def total_slept(self) -> float:
        return sum(self.sleeps)
