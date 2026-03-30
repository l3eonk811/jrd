from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)

    item_tags = relationship("ItemTag", back_populates="tag")


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    __table_args__ = (
        UniqueConstraint("item_id", "tag_id", name="uq_item_tag"),
    )

    item = relationship("Item", back_populates="item_tags")
    tag = relationship("Tag", back_populates="item_tags")
