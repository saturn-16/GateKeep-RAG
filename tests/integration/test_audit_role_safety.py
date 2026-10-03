import os
import pytest
from sqlalchemy import create_engine, text

pytest.importorskip("sqlalchemy")

from app.config import get_settings

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(
    os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres",
    reason="requires live PostgreSQL service",
)
def test_app_role_cannot_own_audit_table_or_disable_triggers() -> None:
    settings = get_settings()
    # Connect as gatekeep_app (non-owner application role)
    base_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    # Substitute user gatekeep_app
    app_url = base_url.replace("gatekeep:gatekeep@", "gatekeep_app:gatekeep@")

    engine = create_engine(app_url)
    with engine.connect() as conn:
        # 1. Non-owner can read audit logs
        count = conn.execute(text("SELECT count(*) FROM audit_logs")).scalar()
        assert count is not None

        # 2. Non-owner CANNOT disable triggers on audit_logs (PostgreSQL requires table ownership)
        with pytest.raises(Exception) as exc_info:
            conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER ALL"))
        assert "must be owner of table audit_logs" in str(exc_info.value).lower()
        conn.rollback()

        # 3. Non-owner CANNOT delete from audit_logs
        with pytest.raises(Exception) as exc_info:
            conn.execute(text("DELETE FROM audit_logs WHERE id='non-existent'"))
        err_msg = str(exc_info.value).lower()
        assert "permission denied" in err_msg or "append-only" in err_msg
        conn.rollback()

        # 4. Non-owner CANNOT update audit_logs
        with pytest.raises(Exception) as exc_info:
            conn.execute(text("UPDATE audit_logs SET action='tamper' WHERE id='non-existent'"))
        err_msg = str(exc_info.value).lower()
        assert "permission denied" in err_msg or "append-only" in err_msg
