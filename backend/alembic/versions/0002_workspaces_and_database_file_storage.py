"""workspaces and database file storage

- documents.workspace_id: anonymous per-browser demo workspaces (DEMO_MODE).
- stored_files: file bytes for STORAGE_BACKEND=database (hosts without a persistent disk).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29 05:48:12.636368
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_stored_files")),
    )
    # Existing documents (created before workspaces existed) belong to the local workspace.
    op.add_column(
        "documents",
        sa.Column("workspace_id", sa.String(length=64), server_default="local", nullable=False),
    )
    op.create_index(op.f("ix_documents_workspace_id"), "documents", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_workspace_id"), table_name="documents")
    op.drop_column("documents", "workspace_id")
    op.drop_table("stored_files")
