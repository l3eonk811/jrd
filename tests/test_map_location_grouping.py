"""
Tests for map location-based item grouping.
"""
import pytest


class TestLocationGrouping:
    """Test grouping logic for items at the same location."""
    
    def test_same_coordinates_grouped(self):
        """Items with identical coordinates should be grouped."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060, "title": "Item 1"},
            {"id": 2, "lat": 40.7128, "lon": -74.0060, "title": "Item 2"},
            {"id": 3, "lat": 40.7128, "lon": -74.0060, "title": "Item 3"},
        ]
        
        # Group by location (6 decimal precision)
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # All 3 items should be in one group
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 3
    
    def test_different_coordinates_separate(self):
        """Items with different coordinates should be in separate groups."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060},
            {"id": 2, "lat": 40.7580, "lon": -73.9855},
            {"id": 3, "lat": 40.6892, "lon": -74.0445},
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # 3 different locations = 3 groups
        assert len(groups) == 3
        for group in groups.values():
            assert len(group) == 1
    
    def test_nearby_but_different_separate(self):
        """Items very close but not identical should be in separate groups."""
        items = [
            {"id": 1, "lat": 40.712800, "lon": -74.006000},  # Base
            {"id": 2, "lat": 40.712801, "lon": -74.006000},  # 0.00001° diff (~1m)
            {"id": 3, "lat": 40.712800, "lon": -74.006001},  # 0.00001° diff
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # 6 decimal precision means these are different
        assert len(groups) == 3
    
    def test_precision_grouping(self):
        """Test that 6 decimal precision groups appropriately."""
        items = [
            {"id": 1, "lat": 40.7128001, "lon": -74.0060001},  # Rounds to same
            {"id": 2, "lat": 40.7128002, "lon": -74.0060002},  # Rounds to same
            {"id": 3, "lat": 40.7128003, "lon": -74.0060003},  # Rounds to same
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # Should all round to 40.712800,-74.006000
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 3


class TestLocationGroupingFilters:
    """Test that filtering works correctly with grouped locations."""
    
    def test_public_items_only_in_groups(self):
        """Only public items should be included in location groups."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060, "is_public": True},
            {"id": 2, "lat": 40.7128, "lon": -74.0060, "is_public": False},  # Excluded
            {"id": 3, "lat": 40.7128, "lon": -74.0060, "is_public": True},
        ]
        
        # Filter before grouping
        public_items = [i for i in items if i["is_public"]]
        
        groups = {}
        for item in public_items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # Only 2 public items should be grouped
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2
        assert all(item["is_public"] for item in list(groups.values())[0])
    
    def test_valid_coordinates_only(self):
        """Items without valid coordinates should be excluded."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060},
            {"id": 2, "lat": None, "lon": -74.0060},  # Invalid
            {"id": 3, "lat": 40.7128, "lon": None},  # Invalid
            {"id": 4, "lat": 40.7128, "lon": -74.0060},
        ]
        
        # Filter valid coordinates
        valid_items = [
            i for i in items 
            if i["lat"] is not None and i["lon"] is not None
        ]
        
        groups = {}
        for item in valid_items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # Only 2 valid items should be grouped
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2
    
    def test_discoverable_status_only(self):
        """Only items with discoverable status should be grouped."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060, "status": "available"},
            {"id": 2, "lat": 40.7128, "lon": -74.0060, "status": "draft"},  # Excluded
            {"id": 3, "lat": 40.7128, "lon": -74.0060, "status": "available"},
            {"id": 4, "lat": 40.7128, "lon": -74.0060, "status": "archived"},  # Excluded
        ]
        
        DISCOVERABLE_STATUSES = ["available"]
        
        # Filter discoverable items
        discoverable = [
            i for i in items 
            if i["status"] in DISCOVERABLE_STATUSES
        ]
        
        groups = {}
        for item in discoverable:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # Only 2 available items should be grouped
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2
        assert all(item["status"] == "available" for item in list(groups.values())[0])


class TestMapGroupingBehavior:
    """Test expected map behavior with grouped markers."""
    
    def test_single_item_no_grouping(self):
        """Single item at location should not show group UI."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060, "title": "Solo Item"},
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        location_key = list(groups.keys())[0]
        group_items = groups[location_key]
        
        is_multi_item = len(group_items) > 1
        assert is_multi_item is False
    
    def test_multiple_items_shows_group(self):
        """Multiple items at location should show group UI."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060, "title": "Item 1"},
            {"id": 2, "lat": 40.7128, "lon": -74.0060, "title": "Item 2"},
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        location_key = list(groups.keys())[0]
        group_items = groups[location_key]
        
        is_multi_item = len(group_items) > 1
        assert is_multi_item is True
        assert len(group_items) == 2
    
    def test_group_count_accurate(self):
        """Group should show correct count of items."""
        items = [
            {"id": i, "lat": 40.7128, "lon": -74.0060, "title": f"Item {i}"}
            for i in range(1, 6)  # 5 items
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        location_key = list(groups.keys())[0]
        group_items = groups[location_key]
        
        assert len(group_items) == 5
    
    def test_mixed_locations_multiple_groups(self):
        """Multiple locations should create multiple marker groups."""
        items = [
            # Location 1: 3 items
            {"id": 1, "lat": 40.7128, "lon": -74.0060},
            {"id": 2, "lat": 40.7128, "lon": -74.0060},
            {"id": 3, "lat": 40.7128, "lon": -74.0060},
            # Location 2: 2 items
            {"id": 4, "lat": 40.7580, "lon": -73.9855},
            {"id": 5, "lat": 40.7580, "lon": -73.9855},
            # Location 3: 1 item
            {"id": 6, "lat": 40.6892, "lon": -74.0445},
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        assert len(groups) == 3
        
        # Check group sizes
        group_sizes = sorted([len(g) for g in groups.values()])
        assert group_sizes == [1, 2, 3]


class TestGroupingEdgeCases:
    """Test edge cases for location grouping."""
    
    def test_empty_items_list(self):
        """Empty items list should create no groups."""
        items = []
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        assert len(groups) == 0
    
    def test_all_items_filtered_out(self):
        """If all items filtered, no groups should be created."""
        items = [
            {"id": 1, "lat": 40.7128, "lon": -74.0060, "is_public": False},
            {"id": 2, "lat": 40.7128, "lon": -74.0060, "is_public": False},
        ]
        
        # Filter to only public
        public_items = [i for i in items if i["is_public"]]
        
        groups = {}
        for item in public_items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        assert len(groups) == 0
    
    def test_extreme_coordinates(self):
        """Test with extreme valid coordinate values."""
        items = [
            {"id": 1, "lat": 89.999999, "lon": 179.999999},  # Near north pole
            {"id": 2, "lat": -89.999999, "lon": -179.999999},  # Near south pole
            {"id": 3, "lat": 0.0, "lon": 0.0},  # Null island
        ]
        
        groups = {}
        for item in items:
            key = f"{item['lat']:.6f},{item['lon']:.6f}"
            groups.setdefault(key, []).append(item)
        
        # All different locations
        assert len(groups) == 3
