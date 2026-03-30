from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, Text, Enum, JSON, LargeBinary, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
import math
import struct

from app.database import Base
from app.domain.text_embedding_constants import (
    TEXT_EMBEDDING_DIM,
    TEXT_EMBEDDING_PACKED_BYTES,
    TEXT_EMBEDDING_STRUCT_FMT,
)
from app.domain.text_embedding_errors import (
    CorruptedTextEmbeddingStorageError,
    InvalidTextEmbeddingVectorError,
)


class ItemCondition(str, enum.Enum):
    new = "new"
    like_new = "like_new"
    good = "good"
    fair = "fair"
    poor = "poor"


class ItemStatus(str, enum.Enum):
    """Persisted listing state. Product lifecycle vocabulary (draft / published / hidden / archived / deleted)
    is derived together with ``Item.is_public`` — see ``app.domain.listing_lifecycle``."""

    draft = "draft"
    available = "available"
    reserved = "reserved"
    donated = "donated"
    archived = "archived"
    removed = "removed"


class ListingDomain(str, enum.Enum):
    item = "item"
    service = "service"


class ListingType(str, enum.Enum):
    sale = "sale"
    donation = "donation"
    adoption = "adoption"


class PricingModel(str, enum.Enum):
    hourly = "hourly"
    fixed = "fixed"
    negotiable = "negotiable"


class ServiceMode(str, enum.Enum):
    at_client_location = "at_client_location"
    at_provider_location = "at_provider_location"
    remote = "remote"


# Statuses visible in discover/search/similar (public discovery)
DISCOVERABLE_STATUSES = (ItemStatus.available.value,)


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True, index=True)
    subcategory = Column(String(100), nullable=True)
    condition = Column(Enum(ItemCondition), nullable=True)  # null for services
    status = Column(String(50), nullable=False, default=ItemStatus.available.value, index=True)
    is_public = Column(Boolean, default=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    image_embedding = Column(LargeBinary, nullable=True)
    # Text semantics (Phase S1) — independent from OpenCLIP image_embedding
    text_embedding = Column(LargeBinary, nullable=True)
    text_embedding_updated_at = Column(DateTime(timezone=True), nullable=True)
    semantic_text = Column(Text, nullable=True)
    # SHA-256 hex (64 chars): ``compute_embedding_source_fingerprint`` at last successful embed
    text_embedding_source_hash = Column(String(64), nullable=True)
    # Explicit queue for ``tools.index_text_embeddings`` (no inline embed on create/update).
    text_embedding_needs_reindex = Column(Boolean, nullable=False, default=True)
    text_embedding_reindex_requested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ── listing architecture ─────────────────────────────────────────────────
    listing_domain = Column(String(20), nullable=False, default=ListingDomain.item.value, index=True)
    listing_type = Column(String(20), nullable=True, index=True)   # sale|donation|adoption; null for services
    # Denormalized from service_details.service_category for service listings (controlled vocabulary; see domain.service_categories).
    service_category = Column(String(64), nullable=True, index=True)
    price = Column(Float, nullable=True)
    currency = Column(String(10), nullable=False, default="SAR")

    # ── per-listing contact/privacy controls ─────────────────────────────────
    show_phone_in_listing = Column(Boolean, nullable=False, default=False)
    allow_messages = Column(Boolean, nullable=False, default=True)

    # ── engagement ───────────────────────────────────────────────────────────
    view_count = Column(Integer, nullable=False, default=0, server_default="0")

    # ── relationships ────────────────────────────────────────────────────────
    owner = relationship("User", back_populates="items")
    images = relationship("ItemImage", back_populates="item", cascade="all, delete-orphan")
    item_tags = relationship("ItemTag", back_populates="item", cascade="all, delete-orphan")
    ai_analyses = relationship(
        "ItemAIAnalysis", back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemAIAnalysis.created_at.desc()",
    )
    adoption_details = relationship(
        "AdoptionDetails", back_populates="item",
        uselist=False, cascade="all, delete-orphan"
    )
    service_details = relationship(
        "ServiceDetails", back_populates="item",
        uselist=False, cascade="all, delete-orphan"
    )
    favorited_by = relationship("Favorite", back_populates="item", cascade="all, delete-orphan")

    def set_embedding(self, vector: list[float]) -> None:
        self.image_embedding = struct.pack(f"{len(vector)}f", *vector)

    def get_embedding(self) -> list[float] | None:
        if self.image_embedding is None:
            return None
        count = len(self.image_embedding) // 4
        return list(struct.unpack(f"{count}f", self.image_embedding))

    def set_text_embedding(self, vector: list[float]) -> None:
        """
        Pack exactly ``TEXT_EMBEDDING_DIM`` finite float32 values (little-endian).

        Raises:
            InvalidTextEmbeddingVectorError: ``vector`` is None, wrong length, or non-finite.
        """
        if vector is None:
            raise InvalidTextEmbeddingVectorError(
                "text embedding vector must not be None; use clear_listing_text_embedding() to clear storage"
            )
        if len(vector) != TEXT_EMBEDDING_DIM:
            raise InvalidTextEmbeddingVectorError(
                f"expected {TEXT_EMBEDDING_DIM} floats, got {len(vector)}"
            )
        validated: list[float] = []
        for i, x in enumerate(vector):
            try:
                f = float(x)
            except (TypeError, ValueError) as e:
                raise InvalidTextEmbeddingVectorError(
                    f"element {i} is not float-convertible: {type(x).__name__}"
                ) from e
            if not math.isfinite(f):
                raise InvalidTextEmbeddingVectorError(
                    f"element {i} is not finite: {f!r}"
                )
            validated.append(f)
        self.text_embedding = struct.pack(TEXT_EMBEDDING_STRUCT_FMT, *validated)

    def get_text_embedding(self) -> list[float] | None:
        """
        Unpack stored vector using the same layout as ``set_text_embedding``.

        Returns:
            None if no embedding is stored (``text_embedding`` IS NULL).

        Raises:
            CorruptedTextEmbeddingStorageError: wrong byte length or non-finite unpacked values.
        """
        raw = self.text_embedding
        if raw is None:
            return None
        if len(raw) != TEXT_EMBEDDING_PACKED_BYTES:
            raise CorruptedTextEmbeddingStorageError(
                f"expected {TEXT_EMBEDDING_PACKED_BYTES} bytes, got {len(raw)}"
            )
        vec = list(struct.unpack(TEXT_EMBEDDING_STRUCT_FMT, raw))
        for i, f in enumerate(vec):
            if not math.isfinite(f):
                raise CorruptedTextEmbeddingStorageError(
                    f"unpacked element {i} is not finite: {f!r}"
                )
        return vec

    def clear_listing_text_embedding(self) -> None:
        """Remove text embedding payload and freshness metadata (image_embedding untouched)."""
        self.text_embedding = None
        self.semantic_text = None
        self.text_embedding_source_hash = None
        self.text_embedding_updated_at = None
        # Pending reindex is set by callers (ORM listeners / jobs); avoid duplicating logic here.

    @property
    def tags(self):
        return [it.tag for it in self.item_tags]

    @property
    def latest_ai_analysis(self):
        return self.ai_analyses[0] if self.ai_analyses else None

    @property
    def ai_analysis(self):
        return self.latest_ai_analysis


class AdoptionDetails(Base):
    """Animal-specific fields for adoption listings. 1-to-1 with Item."""
    __tablename__ = "adoption_details"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"),
                     nullable=False, unique=True, index=True)
    animal_type = Column(String(100), nullable=False)
    age = Column(String(50), nullable=True)
    gender = Column(String(20), nullable=True)          # male | female | unknown
    health_status = Column(Text, nullable=True)
    vaccinated_status = Column(String(30), nullable=True)   # vaccinated | not_vaccinated | unknown
    neutered_status = Column(String(30), nullable=True)     # neutered | not_neutered | unknown
    adoption_reason = Column(Text, nullable=True)
    special_experience_required = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    item = relationship("Item", back_populates="adoption_details")


class ServiceDetails(Base):
    """Service-provider-specific fields for service domain listings. 1-to-1 with Item."""
    __tablename__ = "service_details"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"),
                     nullable=False, unique=True, index=True)
    service_category = Column(String(100), nullable=False, index=True)
    pricing_model = Column(String(30), nullable=False, default=PricingModel.negotiable.value)
    service_mode = Column(String(30), nullable=True)
    service_area = Column(String(200), nullable=True)
    availability_notes = Column(Text, nullable=True)
    experience_years = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    item = relationship("Item", back_populates="service_details")


class ItemImage(Base):
    __tablename__ = "item_images"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    item = relationship("Item", back_populates="images")
    ai_analyses = relationship("ItemAIAnalysis", back_populates="image", cascade="all, delete-orphan")


class ItemAIAnalysis(Base):
    __tablename__ = "item_ai_analyses"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id = Column(Integer, ForeignKey("item_images.id", ondelete="SET NULL"), nullable=True)
    suggested_title = Column(String(255), nullable=False)
    suggested_category = Column(String(100), nullable=False)
    suggested_subcategory = Column(String(100), nullable=True)
    suggested_condition = Column(String(50), nullable=False)
    suggested_tags = Column(JSON, nullable=False, default=list)
    suggested_description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=False, default=1.0)
    category_confidence = Column(Float, nullable=True)
    subcategory_confidence = Column(Float, nullable=True)
    used_fallback = Column(Boolean, nullable=False, default=False)
    ai_service = Column(String(50), nullable=False, default="mock")
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    image_size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    item = relationship("Item", back_populates="ai_analyses")
    image = relationship("ItemImage", back_populates="ai_analyses")


class Favorite(Base):
    """User-saved listings."""
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_favorites_user_item"),)

    user = relationship("User", back_populates="favorites")
    item = relationship("Item", back_populates="favorited_by")
