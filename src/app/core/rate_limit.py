from datetime import datetime, timedelta, timezone

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
