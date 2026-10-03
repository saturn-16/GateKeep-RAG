import os
import pytest


@pytest.fixture(autouse=True, scope="function")
def clear_rate_limit_events():
    if os.getenv("PERSISTENCE_BACKEND") == "postgres":
        try:
            from app.db.session import SessionLocal
            from sqlalchemy import text
            with SessionLocal() as session:
                session.execute(text("DELETE FROM rate_limit_events"))
                session.commit()
        except Exception:
            pass
