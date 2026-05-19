import asyncio
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")
Subscriber = Callable[[T], Awaitable[None]]


class Bus(Generic[T]):
    def __init__(self, name: str) -> None:
        self.name = name
        self._subscribers: list[Subscriber[T]] = []

    def subscribe(self, fn: Subscriber[T]) -> None:
        self._subscribers.append(fn)

    async def publish(self, msg: T) -> None:
        if not self._subscribers:
            return
        await asyncio.gather(*(fn(msg) for fn in self._subscribers))
