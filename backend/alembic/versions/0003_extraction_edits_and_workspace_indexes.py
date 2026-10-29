"""extraction edits audit trail and workspace indexes

- extraction_edits: every user correction (and "discard my corrections" resets). Also the
  source of corrections that are re-applied when a document is reprocessed.
- documents (workspace_id, created_at) and (workspace_id, sha256): the list query and
  duplicate detection, both always scoped to one workspace.

Additive only: no existing rows are modified, and downgrade drops just these objects.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_edits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_extraction_edits_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_edits")),
    )
    op.create_index(
        "ix_extraction_edits_document_created",
        "extraction_edits",
        ["document_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_documents_workspace_created", "documents", ["workspace_id", "created_at"], unique=False
    )
    op.create_index("ix_documents_workspace_sha256", "documents", ["workspace_id", "sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_workspace_sha256", table_name="documents")
    op.drop_index("ix_documents_workspace_created", table_name="documents")
    op.drop_index("ix_extraction_edits_document_created", table_name="extraction_edits")
    op.drop_table("extraction_edits")
