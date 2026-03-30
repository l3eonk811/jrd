"""
Tests for item status workflow: draft, available, reserved, donated, archived, removed.
"""

import pytest

# Skip entire module if full app deps (psycopg2) not available
pytest.importorskip("psycopg2")


class TestItemStatusEnum:
    """Test ItemStatus enum values."""

    def test_status_values(self):
        """All expected statuses exist."""
        from app.models.item import ItemStatus
        expected = {"draft", "available", "reserved", "donated", "archived", "removed"}
        actual = {s.value for s in ItemStatus}
        assert expected == actual

    def test_discoverable_statuses(self):
        """Only 'available' is discoverable."""
        from app.models.item import DISCOVERABLE_STATUSES
        assert "available" in DISCOVERABLE_STATUSES
        assert "draft" not in DISCOVERABLE_STATUSES
        assert "archived" not in DISCOVERABLE_STATUSES
        assert "removed" not in DISCOVERABLE_STATUSES


class TestStatusFiltering:
    """Test that discover/search/similar filter by status."""

    def test_discoverable_includes_available(self):
        """Items with status=available are in DISCOVERABLE_STATUSES."""
        from app.models.item import DISCOVERABLE_STATUSES, ItemStatus
        assert ItemStatus.available.value in DISCOVERABLE_STATUSES

    def test_hidden_statuses_excluded(self):
        """Draft, archived, removed are not discoverable."""
        from app.models.item import DISCOVERABLE_STATUSES, ItemStatus
        hidden = [ItemStatus.draft, ItemStatus.archived, ItemStatus.removed]
        for s in hidden:
            assert s.value not in DISCOVERABLE_STATUSES

    def test_reserved_not_discoverable(self):
        """Reserved items are not in discover (claimed)."""
        from app.models.item import DISCOVERABLE_STATUSES, ItemStatus
        assert ItemStatus.reserved.value not in DISCOVERABLE_STATUSES

    def test_donated_not_discoverable(self):
        """Donated items are not in discover (gone)."""
        from app.models.item import DISCOVERABLE_STATUSES, ItemStatus
        assert ItemStatus.donated.value not in DISCOVERABLE_STATUSES


class TestStatusSchema:
    """Test status in Pydantic schemas."""

    def test_item_base_has_status(self):
        """ItemBase includes status field."""
        from app.schemas.item import ItemBase
        assert "status" in ItemBase.model_fields

    def test_item_update_accepts_status(self):
        """ItemUpdate accepts optional status."""
        from app.schemas.item import ItemUpdate
        from app.models.item import ItemStatus
        data = ItemUpdate(status=ItemStatus.archived)
        assert data.status == ItemStatus.archived
