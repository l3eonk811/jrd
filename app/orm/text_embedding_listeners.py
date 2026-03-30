"""
Centralized ORM invalidation for listing text embeddings.

Any change to semantic-source data clears ``text_embedding`` + metadata on the parent
``Item`` so stale vectors cannot remain valid-looking. Covers paths that bypass
``item_service.update_item`` (direct ORM mutation, tag rows, detail tables).

**Limitation:** SQLAlchemy Core ``bulk_update_mappings`` / raw ``UPDATE`` without ORM
instances do not emit these events — document and avoid for semantic fields, or run a reindex.
"""

from __future__ import annotations

import logging

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, object_session

from app.models.item import AdoptionDetails, Item, ServiceDetails
from app.models.tag import ItemTag
from app.services.text_embedding_reindex import mark_item_text_embedding_pending_reindex

log = logging.getLogger(__name__)

_ITEM_SEMANTIC_COLUMNS = frozenset({"title", "category", "subcategory", "description"})


def _clear_te_for_item_id(session: Session | None, item_id: int | None, reason: str) -> None:
    if session is None or item_id is None:
        return
    item = session.get(Item, item_id)
    if item is None:
        return
    if item.text_embedding is not None or item.text_embedding_source_hash is not None:
        item.clear_listing_text_embedding()
    mark_item_text_embedding_pending_reindex(item)
    log.debug(
        "text_embedding_invalidated item_id=%s reason=%s",
        item_id,
        reason,
    )


def _clear_te_for_item(item: Item | None, reason: str) -> None:
    if item is None:
        return
    _clear_te_for_item_id(object_session(item), item.id, reason)


@event.listens_for(Item, "before_update", propagate=True)
def _item_te_before_update(mapper, connection, target: Item) -> None:
    insp = inspect(target)
    for col in _ITEM_SEMANTIC_COLUMNS:
        attr = insp.attrs.get(col)
        if attr is not None and attr.history.has_changes():
            target.clear_listing_text_embedding()
            mark_item_text_embedding_pending_reindex(target)
            log.debug("text_embedding_invalidated item_id=%s reason=item.%s", target.id, col)
            return


@event.listens_for(Session, "before_flush", propagate=True)
def _session_te_itemtags(session: Session, flush_context, instances) -> None:
    for obj in list(session.new):
        if isinstance(obj, ItemTag):
            _clear_te_for_item_id(session, obj.item_id, "item_tags.insert")
    for obj in list(session.deleted):
        if isinstance(obj, ItemTag):
            _clear_te_for_item_id(session, obj.item_id, "item_tags.delete")
    # Detail-table updates: run here (not in mapper before_update) so clearing the parent
    # Item does not nest inside another row's flush and get dropped (SQLAlchemy warns and
    # resets history on the Item).
    for obj in list(session.dirty):
        if isinstance(obj, ServiceDetails):
            insp = inspect(obj)
            attr = insp.attrs.get("service_category")
            if attr is not None and attr.history.has_changes():
                _clear_te_for_item_id(session, obj.item_id, "service_details.service_category")
        elif isinstance(obj, AdoptionDetails):
            insp = inspect(obj)
            attr = insp.attrs.get("animal_type")
            if attr is not None and attr.history.has_changes():
                _clear_te_for_item_id(session, obj.item_id, "adoption_details.animal_type")


@event.listens_for(ServiceDetails, "after_insert", propagate=True)
def _service_details_te_after_insert(mapper, connection, target: ServiceDetails) -> None:
    _clear_te_for_item_id(object_session(target), target.item_id, "service_details.insert")


@event.listens_for(AdoptionDetails, "after_insert", propagate=True)
def _adoption_te_after_insert(mapper, connection, target: AdoptionDetails) -> None:
    _clear_te_for_item_id(object_session(target), target.item_id, "adoption_details.insert")
