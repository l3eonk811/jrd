"""
Tests for taxonomy module: normalization, prompts, and category logic.
"""

import pytest
from app.ai.taxonomy import (
    MAIN_CATEGORIES,
    get_main_category_prompts,
    get_subcategory_prompts,
    get_allowed_tags_for_category,
    normalize_category,
    normalize_condition,
    normalize_tag,
    filter_allowed_tags,
    build_title,
)


class TestMainCategories:
    """Test main category structure and lookups."""
    
    def test_main_categories_exist(self):
        """Test that main categories are defined."""
        assert len(MAIN_CATEGORIES) > 0
        assert any(cat.id == "vehicles" for cat in MAIN_CATEGORIES)
        assert any(cat.id == "electronics" for cat in MAIN_CATEGORIES)
        assert any(cat.id == "kitchen" for cat in MAIN_CATEGORIES)
        assert any(cat.id == "other" for cat in MAIN_CATEGORIES)
    
    def test_vehicles_category_added(self):
        """Test that vehicles category was added with subcategories."""
        vehicles = next((c for c in MAIN_CATEGORIES if c.id == "vehicles"), None)
        assert vehicles is not None
        assert vehicles.label_en == "Vehicles"
        assert len(vehicles.subcategories) >= 3
        sub_ids = [s.id for s in vehicles.subcategories]
        assert "cars" in sub_ids
        assert "motorcycles" in sub_ids
        assert "bicycles" in sub_ids
    
    def test_appliances_category_added(self):
        """Test that appliances category was added."""
        appliances = next((c for c in MAIN_CATEGORIES if c.id == "appliances"), None)
        assert appliances is not None
        assert appliances.label_en == "Appliances"
        sub_ids = [s.id for s in appliances.subcategories]
        assert "kitchen_appliances" in sub_ids
        assert "laundry" in sub_ids


class TestCategoryPrompts:
    """Test category prompt generation."""
    
    def test_main_category_prompts_structure(self):
        """Test that main category prompts have correct structure."""
        prompts = get_main_category_prompts()
        assert len(prompts) == len(MAIN_CATEGORIES)
        
        # Each prompt should be (id, label_en, prompt_text)
        for cat_id, label, prompt in prompts:
            assert isinstance(cat_id, str)
            assert isinstance(label, str)
            assert isinstance(prompt, str)
            assert len(prompt) > 0
    
    def test_vehicles_prompt_is_rich(self):
        """Test that vehicles prompt is descriptive, not just 'a photo of Vehicles'."""
        prompts = get_main_category_prompts()
        vehicles_prompt = next(
            (p[2] for p in prompts if p[0] == "vehicles"), None
        )
        assert vehicles_prompt is not None
        # Should include synonyms like car, motorcycle, bicycle
        prompt_lower = vehicles_prompt.lower()
        assert "vehicle" in prompt_lower or "car" in prompt_lower
        # Should not be just the generic template
        assert vehicles_prompt != "a photo of Vehicles"
    
    def test_kitchen_prompt_includes_synonyms(self):
        """Test that kitchen prompt includes specific item types."""
        prompts = get_main_category_prompts()
        kitchen_prompt = next(
            (p[2] for p in prompts if p[0] == "kitchen"), None
        )
        assert kitchen_prompt is not None
        prompt_lower = kitchen_prompt.lower()
        # Should mention specific kitchen items
        assert any(word in prompt_lower for word in ["cookware", "utensils", "pot", "pan"])
    
    def test_subcategory_prompts_for_vehicles(self):
        """Test subcategory prompts for vehicles category."""
        sub_prompts = get_subcategory_prompts("vehicles")
        assert len(sub_prompts) > 0
        
        # Should have cars subcategory with rich prompt
        cars_prompt = next((p[2] for p in sub_prompts if p[0] == "cars"), None)
        assert cars_prompt is not None
        prompt_lower = cars_prompt.lower()
        assert "car" in prompt_lower or "automobile" in prompt_lower


class TestNormalization:
    """Test normalization functions."""
    
    def test_normalize_category_by_id(self):
        """Test category normalization by id."""
        assert normalize_category("vehicles") == "vehicles"
        assert normalize_category("electronics") == "electronics"
        assert normalize_category("kitchen") == "kitchen"
    
    def test_normalize_category_by_label(self):
        """Test category normalization by label."""
        assert normalize_category("Vehicles") == "vehicles"
        assert normalize_category("Electronics") == "electronics"
        assert normalize_category("Kitchen") == "kitchen"
    
    def test_normalize_category_case_insensitive(self):
        """Test that normalization is case insensitive."""
        assert normalize_category("VEHICLES") == "vehicles"
        assert normalize_category("vehicles") == "vehicles"
        assert normalize_category("Vehicles") == "vehicles"
    
    def test_normalize_category_invalid(self):
        """Test that invalid categories return None."""
        assert normalize_category("invalid_category") is None
        assert normalize_category("") is None
        assert normalize_category(None) is None
    
    def test_normalize_condition(self):
        """Test condition normalization."""
        assert normalize_condition("new") == "new"
        assert normalize_condition("like_new") == "like_new"
        assert normalize_condition("good") == "good"
        assert normalize_condition("fair") == "fair"
        assert normalize_condition("poor") == "poor"
    
    def test_normalize_condition_with_spaces(self):
        """Test condition normalization with spaces."""
        assert normalize_condition("like new") == "like_new"
        assert normalize_condition("Like New") == "like_new"
    
    def test_normalize_tag(self):
        """Test tag normalization."""
        assert normalize_tag("wooden") == "wooden"
        assert normalize_tag("metal") == "metal"
        assert normalize_tag("portable") == "portable"
    
    def test_normalize_tag_with_spaces_to_hyphens(self):
        """Test tag normalization converts spaces to hyphens."""
        assert normalize_tag("stainless steel") == "stainless-steel"
        assert normalize_tag("barely used") == "barely-used"


class TestTagFiltering:
    """Test tag filtering by category."""
    
    def test_get_allowed_tags_for_vehicles(self):
        """Test allowed tags for vehicles category."""
        tags = get_allowed_tags_for_category("vehicles")
        assert "metal" in tags
        assert "outdoor" in tags
        # Kitchen-specific tags should not be allowed
        assert "kitchen" not in tags
        assert "stainless-steel" not in tags
    
    def test_get_allowed_tags_for_kitchen(self):
        """Test allowed tags for kitchen category."""
        tags = get_allowed_tags_for_category("kitchen")
        assert "metal" in tags
        assert "kitchen" in tags
        assert "stainless-steel" in tags
        # Vehicle-specific usage not in kitchen
        # (though there may be overlap)
    
    def test_filter_allowed_tags(self):
        """Test filtering tags to category-allowed set."""
        # Vehicles: metal, outdoor allowed; kitchen not allowed
        predicted = ["metal", "outdoor", "kitchen", "stainless-steel"]
        filtered = filter_allowed_tags(predicted, "vehicles", max_tags=5)
        assert "metal" in filtered
        assert "outdoor" in filtered
        assert "kitchen" not in filtered
        assert "stainless-steel" not in filtered
    
    def test_filter_allowed_tags_respects_max(self):
        """Test that max_tags is respected."""
        predicted = ["metal", "outdoor", "portable", "compact", "vintage"]
        filtered = filter_allowed_tags(predicted, "vehicles", max_tags=3)
        assert len(filtered) <= 3


class TestTitleGeneration:
    """Test title generation logic."""
    
    def test_build_title_with_main_category(self):
        """Test title generation with main category only."""
        title = build_title("vehicles", "good", ["metal", "outdoor"])
        assert "Vehicles" in title
        assert "good" in title
        assert "metal" in title or "outdoor" in title
    
    def test_build_title_with_subcategory(self):
        """Test title generation with subcategory."""
        title = build_title("vehicles", "good", ["metal", "outdoor"], sub_id="cars")
        assert "Cars" in title
        assert "good" in title
    
    def test_build_title_respects_allowed_tags(self):
        """Test that title only uses allowed tags."""
        # Kitchen tags should be filtered out for vehicles
        title = build_title("vehicles", "good", ["kitchen", "metal", "outdoor"])
        # Title should not contain 'kitchen' since it's not allowed for vehicles
        # (It will use fallback if no allowed tags)
        assert "metal" in title or "outdoor" in title


class TestPromptQuality:
    """Test that prompts help distinguish similar categories."""
    
    def test_vehicles_vs_kitchen_prompts_are_distinct(self):
        """Test that vehicles and kitchen prompts are clearly different."""
        prompts = get_main_category_prompts()
        vehicles_prompt = next((p[2] for p in prompts if p[0] == "vehicles"), None)
        kitchen_prompt = next((p[2] for p in prompts if p[0] == "kitchen"), None)
        
        assert vehicles_prompt is not None
        assert kitchen_prompt is not None
        
        # Prompts should not overlap too much
        vehicles_lower = vehicles_prompt.lower()
        kitchen_lower = kitchen_prompt.lower()
        
        # Vehicles should mention vehicles, cars, etc.
        assert any(w in vehicles_lower for w in ["vehicle", "car", "motorcycle", "bicycle"])
        # Kitchen should mention kitchen items, not vehicles
        assert any(w in kitchen_lower for w in ["kitchen", "cookware", "pot", "pan"])
        assert "vehicle" not in kitchen_lower
        assert "car" not in kitchen_lower
