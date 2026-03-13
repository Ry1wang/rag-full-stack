"""Add content_hash to documentchunk for embedding cache

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-13 12:00:00.000000

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documentchunk",
        sa.Column(
            "content_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_documentchunk_content_hash", "documentchunk", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_documentchunk_content_hash", table_name="documentchunk")
    op.drop_column("documentchunk", "content_hash")
