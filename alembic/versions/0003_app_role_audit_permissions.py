"""configure non-owner application role and audit permissions"""

from alembic import op

revision = "0003_app_role_audit_permissions"
down_revision = "0002_document_repair_flag"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gatekeep_app') THEN
                CREATE ROLE gatekeep_app WITH LOGIN PASSWORD 'gatekeep' NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
        END $$;
        GRANT CONNECT ON DATABASE gatekeep TO gatekeep_app;
        GRANT USAGE ON SCHEMA public TO gatekeep_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gatekeep_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_logs FROM gatekeep_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gatekeep_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO gatekeep_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO gatekeep_app;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM gatekeep_app;
        REVOKE ALL PRIVILEGES ON SCHEMA public FROM gatekeep_app;
        REVOKE CONNECT ON DATABASE gatekeep FROM gatekeep_app;
        DROP ROLE IF EXISTS gatekeep_app;
        """)
