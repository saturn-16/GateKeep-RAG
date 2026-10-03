"""initial tenant-aware schema"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None


def upgrade() -> None:
    op.create_table("tenants", sa.Column("id", sa.String(100), primary_key=True), sa.Column("name", sa.String(200), nullable=False, unique=True), sa.Column("log_raw_queries", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("users", sa.Column("id", sa.String(100), primary_key=True), sa.Column("tenant_id", sa.String(100), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("password_hash", sa.String(500), nullable=False), sa.Column("clearance", sa.String(30), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("roles", sa.JSON(), nullable=False))
    op.create_table("roles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(100), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("implies", sa.JSON(), nullable=False))
    op.create_table("documents", sa.Column("id", sa.String(100), primary_key=True), sa.Column("tenant_id", sa.String(100), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("title", sa.String(300), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("source", sa.String(500), nullable=False), sa.Column("created_by", sa.String(100), nullable=False), sa.Column("error", sa.Text()))
    op.create_table("chunks", sa.Column("id", sa.String(100), primary_key=True), sa.Column("tenant_id", sa.String(100), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("document_id", sa.String(100), sa.ForeignKey("documents.id"), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("allowed_roles", sa.JSON(), nullable=False), sa.Column("allowed_users", sa.JSON(), nullable=False), sa.Column("sensitivity", sa.String(30), nullable=False), sa.Column("page", sa.Integer()))
    op.create_table("audit_logs", sa.Column("id", sa.String(100), primary_key=True), sa.Column("tenant_id", sa.String(100), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("user_id", sa.String(100), nullable=False), sa.Column("action", sa.String(50), nullable=False), sa.Column("details", sa.JSON(), nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("prev_hash", sa.String(64), nullable=False), sa.Column("row_hash", sa.String(64), nullable=False, unique=True))
    op.create_table("rate_limit_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("key", sa.String(250), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"])
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.execute("CREATE OR REPLACE FUNCTION deny_audit_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END; $$ LANGUAGE plpgsql")
    op.execute("CREATE TRIGGER audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION deny_audit_mutation()")


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("rate_limit_events")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("tenants")
