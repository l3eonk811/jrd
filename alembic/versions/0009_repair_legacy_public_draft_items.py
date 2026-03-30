"""repair legacy public draft items

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-17

Description:
This migration fixes a data inconsistency caused by a schema bug where public items
were incorrectly assigned status='draft' instead of status='available'.

Root Cause:
- Prior to schema fix, ItemBase had: status: ItemStatus = ItemStatus.draft
- This forced all items to status='draft' regardless of is_public setting
- Backend inference logic (public → available, private → draft) never ran

Impact:
- Public items with status='draft' are excluded from Discover and Map
- DISCOVERABLE_STATUSES = ('available',) means only available items are shown

Fix Scope:
- Updates items where is_public=True AND status='draft' to status='available'
- Does NOT touch private items (is_public=False)
- Does NOT touch items with other statuses (reserved, donated, archived, removed)
- Only fixes the specific inconsistency introduced by the schema bug

Expected Behavior After Fix:
- Public items: status='available' → discoverable
- Private items: status='draft' → not discoverable (correct)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get connection for logging
    connection = op.get_bind()
    
    # Count affected items before update
    result = connection.execute(
        text("SELECT COUNT(*) FROM items WHERE is_public = true AND status = 'draft'")
    )
    count_before = result.scalar()
    
    print(f"\n{'='*80}")
    print(f"MIGRATION 0009: Repair Legacy Public Draft Items")
    print(f"{'='*80}")
    print(f"Items matching criteria (is_public=true AND status='draft'): {count_before}")
    
    if count_before > 0:
        # Update public draft items to available
        connection.execute(
            text("""
                UPDATE items 
                SET status = 'available' 
                WHERE is_public = true 
                  AND status = 'draft'
            """)
        )
        
        # Verify the update
        result = connection.execute(
            text("SELECT COUNT(*) FROM items WHERE is_public = true AND status = 'available'")
        )
        count_after = result.scalar()
        
        print(f"✓ Updated {count_before} items to status='available'")
        print(f"✓ Total public available items: {count_after}")
    else:
        print("✓ No legacy items found - database is clean")
    
    print(f"{'='*80}\n")


def downgrade() -> None:
    """
    Downgrade is intentionally conservative.
    
    We cannot safely revert status='available' → 'draft' because:
    1. Some items may have been created as available after this migration
    2. We cannot distinguish between repaired items and legitimately available items
    
    If rollback is absolutely necessary, restore from backup before running this migration.
    """
    print("\n" + "="*80)
    print("WARNING: Downgrade not implemented for migration 0009")
    print("="*80)
    print("This migration cannot be safely reverted because:")
    print("1. Cannot distinguish repaired items from newly created available items")
    print("2. Rolling back would break legitimately public items")
    print("")
    print("If you need to undo this migration:")
    print("1. Restore database from backup taken before upgrade")
    print("2. Or manually review and revert specific items if needed")
    print("="*80 + "\n")
    
    # Don't actually change any data on downgrade
    pass
