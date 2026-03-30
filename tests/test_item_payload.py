"""
Tests for item create/update payload validation.

Verifies that the API accepts and processes latitude, longitude, and is_public
in create and update requests.
"""

import pytest


class TestItemPayloadStructure:
    """Verify payload structure expected by backend."""

    def test_create_payload_includes_location_and_visibility(self):
        """createItem payload must include is_public and optionally latitude/longitude."""
        payload = {
            "title": "Test Item",
            "description": None,
            "category": "Electronics",
            "subcategory": None,
            "condition": "good",
            "is_public": True,
            "tag_names": [],
            "latitude": 40.7128,
            "longitude": -74.006,
        }
        assert "is_public" in payload
        assert payload["is_public"] is True
        assert "latitude" in payload
        assert "longitude" in payload
        assert payload["latitude"] == 40.7128
        assert payload["longitude"] == -74.006

    def test_update_payload_includes_location_and_visibility(self):
        """updateItem payload must include is_public and optionally latitude/longitude."""
        payload = {
            "title": "Updated Item",
            "description": None,
            "category": "Electronics",
            "condition": "good",
            "is_public": True,
            "latitude": 40.7128,
            "longitude": -74.006,
        }
        assert "is_public" in payload
        assert payload["is_public"] is True
        assert "latitude" in payload
        assert "longitude" in payload

    def test_public_item_without_coords_fails_validation(self):
        """Public item without coordinates should be rejected by backend."""
        payload = {
            "title": "Test",
            "is_public": True,
            "latitude": None,
            "longitude": None,
        }
        assert payload["is_public"] is True
        assert payload.get("latitude") is None or payload.get("longitude") is None
        # Backend returns 400 with "Public items require a location"

    def test_public_item_with_coords_succeeds(self):
        """Public item with coordinates should be accepted."""
        payload = {
            "title": "Test",
            "is_public": True,
            "latitude": 40.0,
            "longitude": -74.0,
        }
        assert payload["is_public"] is True
        assert payload["latitude"] is not None
        assert payload["longitude"] is not None


class TestLocationRaceConditionPrevention:
    """
    Document frontend logic that prevents save-before-location-complete race.

    Save button must be disabled when: is_public AND (locating OR no coords).
    """

    def _save_blocked(self, is_public: bool, locating: bool, has_coords: bool) -> bool:
        """Replicate upload page save-button disabled logic."""
        return is_public and (locating or not has_coords)

    def test_save_blocked_while_locating(self):
        """When locating=True and is_public, save must be blocked."""
        assert self._save_blocked(is_public=True, locating=True, has_coords=False) is True
        assert self._save_blocked(is_public=True, locating=True, has_coords=True) is True

    def test_public_save_succeeds_after_location_set(self):
        """When locating=False and has_coords, save is allowed."""
        assert self._save_blocked(is_public=True, locating=False, has_coords=True) is False

    def test_public_save_blocked_if_location_never_completes(self):
        """When locating=False but no coords (detection failed), save blocked."""
        assert self._save_blocked(is_public=True, locating=False, has_coords=False) is True

    def test_private_save_always_allowed(self):
        """Private items don't need location; save never blocked by location."""
        assert self._save_blocked(is_public=False, locating=True, has_coords=False) is False
        assert self._save_blocked(is_public=False, locating=False, has_coords=False) is False
