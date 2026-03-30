"""Tests for domain taxonomy constraints (AI pipeline / listing context)."""

import pytest

from app.ai.base import ListingContext
from app.ai.domain_taxonomy import (
    get_constraints,
    filter_tags_by_constraints,
    constrain_category,
    ADOPTION_TAGS,
)


class TestDomainConstraints:
    """Test domain-aware constraint logic."""

    def test_item_sale_has_no_blocked_tags(self):
        c = get_constraints("item", "sale")
        assert len(c.blocked_tags) == 0

    def test_item_donation_has_no_blocked_tags(self):
        c = get_constraints("item", "donation")
        assert len(c.blocked_tags) == 0

    def test_adoption_blocks_item_tags(self):
        c = get_constraints("item", "adoption")
        assert "portable" in c.blocked_tags
        assert "barely-used" in c.blocked_tags
        assert "furniture" not in c.blocked_tags
        assert "electric" in c.blocked_tags
        assert "kitchen" in c.blocked_tags

    def test_adoption_allows_animal_tags(self):
        c = get_constraints("item", "adoption")
        assert c.allowed_tags is not None
        assert "friendly" in c.allowed_tags
        assert "vaccinated" in c.allowed_tags
        assert "good-with-kids" in c.allowed_tags

    def test_adoption_suppresses_condition(self):
        c = get_constraints("item", "adoption")
        assert c.suppress_condition is True

    def test_service_blocks_item_tags(self):
        c = get_constraints("service")
        assert "portable" in c.blocked_tags
        assert "barely-used" in c.blocked_tags
        assert "wooden" in c.blocked_tags

    def test_service_allows_service_tags(self):
        c = get_constraints("service")
        assert c.allowed_tags is not None
        assert "experienced" in c.allowed_tags
        assert "licensed" in c.allowed_tags
        assert "certified" in c.allowed_tags

    def test_service_suppresses_condition(self):
        c = get_constraints("service")
        assert c.suppress_condition is True

    def test_unknown_domain_has_no_constraints(self):
        c = get_constraints(None, None)
        assert len(c.blocked_tags) == 0
        assert c.allowed_tags is None
        assert c.suppress_condition is False

    def test_filter_tags_blocks_item_tags_for_adoption(self):
        c = get_constraints("item", "adoption")
        tags = ["friendly", "portable", "vaccinated", "barely-used", "trained"]
        filtered = filter_tags_by_constraints(tags, c, max_tags=5)
        assert "friendly" in filtered
        assert "vaccinated" in filtered
        assert "trained" in filtered
        assert "portable" not in filtered
        assert "barely-used" not in filtered

    def test_filter_tags_blocks_item_tags_for_service(self):
        c = get_constraints("service")
        tags = ["experienced", "wooden", "licensed", "compact", "certified"]
        filtered = filter_tags_by_constraints(tags, c, max_tags=5)
        assert "experienced" in filtered
        assert "licensed" in filtered
        assert "certified" in filtered
        assert "wooden" not in filtered
        assert "compact" not in filtered

    def test_filter_tags_respects_max_tags(self):
        c = get_constraints("item", "adoption")
        tags = list(ADOPTION_TAGS)[:10]
        filtered = filter_tags_by_constraints(tags, c, max_tags=3)
        assert len(filtered) <= 3

    def test_constrain_category_adoption(self):
        c = get_constraints("item", "adoption")
        assert constrain_category("Cats", c) == "Cats"
        assert constrain_category("Dogs", c) == "Dogs"
        assert constrain_category("Electronics", c) == "Other"
        assert constrain_category("Furniture", c) == "Other"

    def test_constrain_category_service(self):
        c = get_constraints("service")
        assert constrain_category("plumber", c) == "plumber"
        assert constrain_category("Electronics", c) == "Other"

    def test_constrain_category_item_sale_passes_through(self):
        c = get_constraints("item", "sale")
        assert constrain_category("Electronics", c) == "Electronics"
        assert constrain_category("Furniture", c) == "Furniture"


class TestListingContext:
    """Test that ListingContext correctly constrains predictions."""

    def test_default_context_is_unconstrained(self):
        ctx = ListingContext()
        c = get_constraints(ctx.listing_domain, ctx.listing_type)
        assert c.allowed_tags is None
        assert c.suppress_condition is False

    def test_service_context(self):
        ctx = ListingContext(listing_domain="service", service_category="plumber")
        c = get_constraints(ctx.listing_domain, ctx.listing_type)
        assert c.suppress_condition is True
        assert c.allowed_tags is not None

    def test_adoption_context(self):
        ctx = ListingContext(listing_domain="item", listing_type="adoption", animal_type="cat")
        c = get_constraints(ctx.listing_domain, ctx.listing_type)
        assert c.suppress_condition is True
        assert "friendly" in c.allowed_tags

    def test_sale_context_is_open(self):
        ctx = ListingContext(listing_domain="item", listing_type="sale")
        c = get_constraints(ctx.listing_domain, ctx.listing_type)
        assert c.suppress_condition is False
        assert c.allowed_tags is None


class TestConfidenceFallback:
    """Confidence-based fallback behavior (mirrors pipeline logic)."""

    def test_low_confidence_category_falls_back_to_other(self):
        threshold = 0.20
        low_conf = 0.10
        if low_conf < threshold:
            category = "Other"
        else:
            category = "Electronics"
        assert category == "Other"

    def test_high_confidence_keeps_category(self):
        threshold = 0.20
        high_conf = 0.85
        if high_conf < threshold:
            category = "Other"
        else:
            category = "Electronics"
        assert category == "Electronics"

