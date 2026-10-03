from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import RateLimitEvent


class DatabaseRateLimiter:
    """Fixed-window limiter persisted in PostgreSQL, safe across API workers."""

    def __init__(self, session: Session, limit: int, window_seconds: int = 60) -> None:
        self.session = session
        self.limit = limit
        self.window = timedelta(seconds=window_seconds)

    def allow(self, key: str) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - self.window
        self.session.execute(delete(RateLimitEvent).where(RateLimitEvent.created_at < cutoff))
        count = self.session.scalar(select(func.count()).select_from(RateLimitEvent).where(RateLimitEvent.key == key, RateLimitEvent.created_at >= cutoff)) or 0
        if count >= self.limit:
            self.session.rollback()
            return False
        self.session.add(RateLimitEvent(key=key, created_at=now))
        self.session.commit()
        return True


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[datetime]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_seconds)
        with self._lock:
            self._events[key] = [event for event in self._events[key] if event >= cutoff]
            if len(self._events[key]) >= limit:
                return False
            self._events[key].append(now)
            return True
