"""Clear stored listing text embeddings before 1024-dim multilingual E5 vectors.

Old rows may hold 384×4-byte blobs from the mock-era layout; fingerprinting now
includes ``TEXT_EMBEDDING_DIM``, but clearing payloads avoids corrupt-length reads
and forces a clean reindex after deploy.

Revision ID: 0032
Revises: 0031
Create Date: 2026-03-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE items SET
          text_embedding = NULL,
          semantic_text = NULL,
          text_embedding_source_hash = NULL,
          text_embedding_updated_at = NULL
        WHERE text_embedding IS NOT NULL
        """
    )


def downgrade() -> None:
    # Cannot restore cleared binary payloads.
    pass
