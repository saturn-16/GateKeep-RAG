from collections.abc import Generator

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal


def get_runtime_db() -> Generator[Session | None, None, None]:
    if get_settings().persistence_backend != "postgres":
        yield None
        return
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
