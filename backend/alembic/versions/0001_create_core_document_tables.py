"""create core document tables

Tables: users, documents, document_pages, extracted_fields, line_items,
validation_warnings, processing_jobs.

Enum columns are VARCHAR + one CHECK constraint each, named
ck_<table>_<enum>. The sa.Enum(...) types are rendered with
create_constraint=False because the CHECK constraints are listed explicitly;
autogenerate otherwise emits duplicates.

Revision ID: 0001
Revises:
Create Date: 2026-10-24 01:25:21.041263
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED",
                "PROCESSING",
                "OCR",
                "EXTRACTING",
                "VALIDATING",
                "COMPLETED",
                "NEEDS_REVIEW",
                "FAILED",
                name="document_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "document_type",
            sa.Enum(
                "INVOICE",
                "RECEIPT",
                "UNKNOWN",
                name="document_type",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vendor_name", sa.String(length=255), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("tax", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("discount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("payment_method", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("overall_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "document_type IN ('INVOICE', 'RECEIPT', 'UNKNOWN')", name=op.f("ck_documents_document_type")
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADED', 'PROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING', 'COMPLETED', 'NEEDS_REVIEW', 'FAILED')",
            name=op.f("ck_documents_document_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_documents_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"], unique=False)
    op.create_index(op.f("ix_documents_document_type"), "documents", ["document_type"], unique=False)
    op.create_index(op.f("ix_documents_invoice_date"), "documents", ["invoice_date"], unique=False)
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_index(op.f("ix_documents_user_id"), "documents", ["user_id"], unique=False)
    op.create_index(op.f("ix_documents_vendor_name"), "documents", ["vendor_name"], unique=False)
    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "text_source",
            sa.Enum(
                "EMBEDDED", "OCR", name="text_source", native_enum=False, create_constraint=False, length=32
            ),
            nullable=True,
        ),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("preview_key", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("text_source IN ('EMBEDDED', 'OCR')", name=op.f("ck_document_pages_text_source")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_pages_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint("document_id", "page_number", name=op.f("uq_document_pages_document_id")),
    )
    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "normalized_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "bbox",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("is_user_edited", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_extracted_fields_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extracted_fields")),
        sa.UniqueConstraint("document_id", "name", name=op.f("uq_extracted_fields_document_id")),
    )
    op.create_table(
        "line_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_line_items_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_items")),
    )
    op.create_index(op.f("ix_line_items_document_id"), "line_items", ["document_id"], unique=False)
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                name="job_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "stage",
            sa.Enum(
                "UPLOADED",
                "PROCESSING",
                "OCR",
                "EXTRACTING",
                "VALIDATING",
                "COMPLETED",
                "NEEDS_REVIEW",
                "FAILED",
                name="job_stage",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "stage IN ('UPLOADED', 'PROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING', 'COMPLETED', 'NEEDS_REVIEW', 'FAILED')",
            name=op.f("ck_processing_jobs_job_stage"),
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name=op.f("ck_processing_jobs_job_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_processing_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
    )
    op.create_index(op.f("ix_processing_jobs_document_id"), "processing_jobs", ["document_id"], unique=False)
    op.create_table(
        "validation_warnings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "INFO",
                "WARNING",
                "ERROR",
                name="warning_severity",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR')", name=op.f("ck_validation_warnings_warning_severity")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_validation_warnings_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_warnings")),
    )
    op.create_index(
        op.f("ix_validation_warnings_document_id"), "validation_warnings", ["document_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_validation_warnings_document_id"), table_name="validation_warnings")
    op.drop_table("validation_warnings")
    op.drop_index(op.f("ix_processing_jobs_document_id"), table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index(op.f("ix_line_items_document_id"), table_name="line_items")
    op.drop_table("line_items")
    op.drop_table("extracted_fields")
    op.drop_table("document_pages")
    op.drop_index(op.f("ix_documents_vendor_name"), table_name="documents")
    op.drop_index(op.f("ix_documents_user_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_sha256"), table_name="documents")
    op.drop_index(op.f("ix_documents_invoice_date"), table_name="documents")
    op.drop_index(op.f("ix_documents_document_type"), table_name="documents")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_table("documents")
    op.drop_table("users")
