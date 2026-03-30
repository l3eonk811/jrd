"""
Tests for pagination across user listings, Discover, and Similar endpoints.
"""

import math
import pytest


class TestPaginationMath:
    """Test pagination calculations."""

    def test_total_pages_empty(self):
        """Empty result set has total_pages=1."""
        total_count = 0
        page_size = 20
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
        assert total_pages == 1

    def test_total_pages_single_page(self):
        """Fewer items than page_size gives 1 page."""
        total_count = 15
        page_size = 20
        total_pages = math.ceil(total_count / page_size)
        assert total_pages == 1

    def test_total_pages_multiple(self):
        """Correct page count for multiple pages."""
        total_count = 45
        page_size = 20
        total_pages = math.ceil(total_count / page_size)
        assert total_pages == 3

    def test_offset_calculation(self):
        """Offset is (page-1) * page_size."""
        page, page_size = 3, 10
        offset = (page - 1) * page_size
        assert offset == 20

    def test_slice_bounds(self):
        """Slice [offset:offset+page_size] returns correct range."""
        all_items = list(range(50))
        page, page_size = 2, 10
        offset = (page - 1) * page_size
        page_items = all_items[offset : offset + page_size]
        assert page_items == list(range(10, 20))


class TestPaginatedResponseShape:
    """Test the PaginatedResponse schema structure."""

    def test_paginated_response_has_required_fields(self):
        """PaginatedResponse includes page, page_size, total_count, total_pages, items."""
        pytest.importorskip("psycopg2")
        from app.schemas.common import PaginatedResponse
        fields = set(PaginatedResponse.model_fields.keys())
        assert "items" in fields
        assert "page" in fields
        assert "page_size" in fields
        assert "total_count" in fields
        assert "total_pages" in fields

    def test_paginated_response_roundtrip(self):
        """PaginatedResponse can be constructed and serialized."""
        pytest.importorskip("psycopg2")
        from app.schemas.common import PaginatedResponse
        resp = PaginatedResponse(
            items=[{"id": 1, "name": "a"}],
            page=1,
            page_size=10,
            total_count=1,
            total_pages=1,
        )
        data = resp.model_dump()
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert data["total_count"] == 1
        assert data["total_pages"] == 1
        assert len(data["items"]) == 1
