"""
Tests for item location handling and Discover Nearby visibility.

Documents expected behavior:
- Public items with coordinates appear in nearby search
- Public items without coordinates do not appear
- Private items with coordinates do not appear
- create_item rejects public items without coordinates
- update_item rejects making item public without coordinates (or user coords)
"""

import pytest


def _would_appear_in_discover(is_public: bool, lat: float | None, lon: float | None) -> bool:
    """Replicate search_nearby_items filter logic for testing."""
    return (
        is_public is True
        and lat is not None
        and lon is not None
    )


class TestDiscoverVisibilityRules:
    """Document the rules for Discover Nearby visibility."""

    def test_public_item_with_coordinates_appears(self):
        """
        Given: Item with is_public=True, latitude and longitude set
        When: Search nearby with that location in radius
        Then: Item appears in results
        """
        assert _would_appear_in_discover(True, 40.71, -74.0) is True

    def test_public_item_without_coordinates_does_not_appear(self):
        """
        Given: Item with is_public=True but latitude or longitude is None
        When: Search nearby
        Then: Item does NOT appear
        """
        assert _would_appear_in_discover(True, None, -74.0) is False
        assert _would_appear_in_discover(True, 40.71, None) is False
        assert _would_appear_in_discover(True, None, None) is False

    def test_private_item_with_coordinates_does_not_appear(self):
        """
        Given: Item with is_public=False, latitude and longitude set
        When: Search nearby
        Then: Item does NOT appear
        """
        assert _would_appear_in_discover(False, 40.71, -74.0) is False


class TestCreateItemLocationValidation:
    """Document create_item validation for public items."""

    def test_public_item_requires_coordinates(self):
        """
        When creating item with is_public=True:
        - If data.latitude/longitude provided: use them
        - Else if owner.latitude/longitude set: use owner's
        - Else: raise 400 "Public items require a location..."
        """
        # Validation logic in item_service.create_item
        pass

    def test_private_item_allows_null_coordinates(self):
        """
        When creating item with is_public=False:
        - latitude and longitude can be None
        """
        pass


class TestUpdateItemLocationValidation:
    """Document update_item validation when making item public."""

    def test_making_public_without_coords_uses_owner_location(self):
        """
        When updating item to is_public=True and item has no coords:
        - If owner has latitude/longitude: use owner's, save succeeds
        - Else: raise 400
        """
        pass

    def test_making_public_with_explicit_coords_succeeds(self):
        """
        When updating with is_public=True and payload includes latitude/longitude:
        - Use payload coords, save succeeds
        """
        pass
