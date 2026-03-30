import logging
from typing import List, Optional, Tuple
from sqlalchemy import or_, exists as sql_exists
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from app.models.item import (
    Item, ItemImage, ItemAIAnalysis, ItemStatus, DISCOVERABLE_STATUSES,
    AdoptionDetails, ServiceDetails, ListingDomain, ListingType, PricingModel, ServiceMode,
)
from app.models.tag import Tag, ItemTag
from app.models.user import User
from app.schemas.item import (
    ItemCreate,
    ItemUpdate,
    AdoptionDetailsCreate,
    ServiceDetailsCreate,
    _validate_listing_business_rules,
)
from app.ai.base import AIAnalysisResult
from app.ai.classifier import AIClassificationOutput
from app.utils.geo import haversine_km, approximate_lat_lon_bounds
from app.config import get_settings
from app.domain.service_categories import normalize_legacy_service_category
from app.services.email_verification_service import require_verified_email
from app.services.semantic_text import normalize_free_text_for_embedding_query
from app.services.text_embedding_reindex import mark_item_text_embedding_pending_reindex
from app.services.settings_service import get_default_show_phone_in_listing
log = logging.getLogger(__name__)


def get_or_create_tag(db: Session, name: str) -> Tag:
    name = name.strip().lower()
    tag = db.query(Tag).filter(Tag.name == name).first()
    if not tag:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    return tag


def _item_options():
    """Shared eager-load options used across all item queries."""
    return [
        joinedload(Item.images),
        joinedload(Item.item_tags).joinedload(ItemTag.tag),
        joinedload(Item.ai_analyses),
        joinedload(Item.adoption_details),
        joinedload(Item.service_details),
        joinedload(Item.owner),
    ]


def _apply_adoption_details(db: Session, item: Item, adoption_data) -> None:
    """Create or update AdoptionDetails for an item."""
    existing = item.adoption_details
    data_dict = adoption_data.model_dump()
    if existing:
        for k, v in data_dict.items():
            setattr(existing, k, v)
    else:
        db.add(AdoptionDetails(item_id=item.id, **data_dict))


def _apply_service_details(db: Session, item: Item, service_data) -> None:
    """Create or update ServiceDetails for an item."""
    existing = item.service_details
    data_dict = service_data.model_dump()
    if existing:
        for k, v in data_dict.items():
            setattr(existing, k, v)
    else:
        db.add(ServiceDetails(item_id=item.id, **data_dict))
    item.service_category = data_dict.get("service_category")


def _parse_stored_listing_domain(raw: str) -> ListingDomain:
    try:
        return ListingDomain(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid listing_domain in database: {raw!r}",
        )


def _parse_stored_listing_type(raw: Optional[str]) -> Optional[ListingType]:
    if not raw:
        return None
    try:
        return ListingType(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid listing_type in database: {raw!r}",
        )


def _infer_legacy_listing_type(item: Item) -> ListingType:
    """When item.listing_type is NULL but listing_domain is item — deterministic inference."""
    if item.adoption_details is not None:
        return ListingType.adoption
    if item.price is not None and item.price > 0:
        return ListingType.sale
    return ListingType.donation


def _adoption_create_from_orm(ad: AdoptionDetails) -> AdoptionDetailsCreate:
    return AdoptionDetailsCreate(
        animal_type=ad.animal_type,
        age=ad.age,
        gender=ad.gender,
        health_status=ad.health_status,
        vaccinated_status=ad.vaccinated_status,
        neutered_status=ad.neutered_status,
        adoption_reason=ad.adoption_reason,
        special_experience_required=bool(ad.special_experience_required),
    )


def _service_details_create_from_orm(sd: ServiceDetails) -> ServiceDetailsCreate:
    try:
        pm = PricingModel(sd.pricing_model)
    except ValueError:
        pm = PricingModel.negotiable
    sm: Optional[ServiceMode] = None
    if sd.service_mode:
        try:
            sm = ServiceMode(sd.service_mode)
        except ValueError:
            sm = None
    return ServiceDetailsCreate(
        service_category=normalize_legacy_service_category(sd.service_category),
        pricing_model=pm,
        service_mode=sm,
        service_area=sd.service_area,
        availability_notes=sd.availability_notes,
        experience_years=sd.experience_years,
    )


def create_item(db: Session, data: ItemCreate, owner: User) -> Item:
    if data.is_public:
        require_verified_email(owner, "create public items")

    lat = data.latitude if data.latitude is not None else owner.latitude
    lon = data.longitude if data.longitude is not None else owner.longitude

    if data.is_public and (lat is None or lon is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public listings require a location.",
        )

    incoming_status = data.status
    if incoming_status is None:
        final_status = ItemStatus.available if data.is_public else ItemStatus.draft
    else:
        final_status = incoming_status

    # Default allow_messages for adoption/service
    allow_msgs = data.allow_messages
    if data.listing_domain == ListingDomain.service or (
        data.listing_domain == ListingDomain.item
        and data.listing_type == ListingType.adoption
    ):
        if allow_msgs is None:
            allow_msgs = True

    # AI Enrichment: Assign category, subcategory, tags automatically at publish time
    enrichment_category = data.category
    enrichment_subcategory = data.subcategory
    enrichment_tags = data.tag_names or []
    
    # Only run enrichment if publishing (is_public=True)
    if data.is_public:
        from app.ai.enrichment import enrich_listing
        import logging
        log = logging.getLogger(__name__)
        
        try:
            # Extract service/adoption fields for enrichment
            service_cat = None
            animal_t = None
            if data.service_details:
                service_cat = data.service_details.service_category
            if data.adoption_details:
                animal_t = data.adoption_details.animal_type
            
            result = enrich_listing(
                title=data.title,
                description=data.description,
                listing_domain=data.listing_domain.value,
                listing_type=data.listing_type.value if data.listing_type else None,
                service_category=service_cat,
                animal_type=animal_t,
            )
            
            # Category/subcategory from AI; tags stay user-controlled (tag_names only).
            enrichment_category = result.category
            enrichment_subcategory = result.subcategory
            
            log.info(
                "AI enrichment: item_id=pending category=%s subcategory=%s tags=%s confidence=%.2f method=%s",
                result.category, result.subcategory, result.tags, result.confidence, result.method
            )
        except Exception as e:
            log.warning("AI enrichment failed (using defaults): %s", e)
            # Fallback to safe defaults
            if not enrichment_category:
                from app.ai.enrichment import _get_default_category
                enrichment_category = _get_default_category(
                    data.listing_domain.value,
                    data.listing_type.value if data.listing_type else None
                )

    show_phone = (
        data.show_phone_in_listing
        if data.show_phone_in_listing is not None
        else get_default_show_phone_in_listing(db)
    )

    svc_cat = None
    if data.listing_domain == ListingDomain.service and data.service_details:
        svc_cat = data.service_details.service_category

    item = Item(
        user_id=owner.id,
        title=data.title,
        description=data.description,
        category=enrichment_category,
        subcategory=enrichment_subcategory,
        condition=data.condition.value if data.condition else None,
        status=final_status.value if hasattr(final_status, "value") else final_status,
        is_public=data.is_public,
        latitude=lat,
        longitude=lon,
        listing_domain=data.listing_domain.value,
        listing_type=data.listing_type.value if data.listing_type else None,
        service_category=svc_cat,
        price=data.price,
        currency=data.currency,
        show_phone_in_listing=show_phone,
        allow_messages=allow_msgs if allow_msgs is not None else True,
    )
    db.add(item)
    db.flush()
    mark_item_text_embedding_pending_reindex(item)

    # Add AI-assigned tags
    for tag_name in enrichment_tags:
        tag = get_or_create_tag(db, tag_name)
        db.add(ItemTag(item_id=item.id, tag_id=tag.id))

    if data.adoption_details:
        _apply_adoption_details(db, item, data.adoption_details)

    if data.service_details:
        _apply_service_details(db, item, data.service_details)

    db.commit()
    return get_item(db, item.id)


def get_item(db: Session, item_id: int) -> Optional[Item]:
    return (
        db.query(Item)
        .options(*_item_options())
        .filter(Item.id == item_id)
        .first()
    )


def get_user_items(
    db: Session,
    user_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    status_bucket: Optional[str] = None,
) -> tuple[List[Item], int]:
    """
    status_bucket: all | active | draft | reserved | donated | archived
    - active -> available only
    - archived -> archived or removed
    """
    base_q = db.query(Item).filter(Item.user_id == user_id)
    bucket = (status_bucket or "all").strip().lower()
    if bucket and bucket != "all":
        if bucket == "active":
            base_q = base_q.filter(Item.status == ItemStatus.available.value)
        elif bucket == "archived":
            base_q = base_q.filter(
                Item.status.in_([ItemStatus.archived.value, ItemStatus.removed.value])
            )
        elif bucket in (
            ItemStatus.draft.value,
            ItemStatus.reserved.value,
            ItemStatus.donated.value,
        ):
            base_q = base_q.filter(Item.status == bucket)
        # unknown buckets ignored (treat as all)
    total_count = base_q.count()
    offset = (page - 1) * page_size
    items = (
        base_q.options(*_item_options())
        .order_by(Item.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return items, total_count


def update_item(db: Session, item_id: int, data: ItemUpdate, owner: User) -> Item:
    item = get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your item")

    # Track if this is a draft->public transition
    was_private = not item.is_public
    will_be_public = data.is_public if data.is_public is not None else item.is_public

    # Determine final domain/type/price for validation (merge payload + DB; never rely on payload alone).
    final_domain = (
        data.listing_domain if data.listing_domain is not None else _parse_stored_listing_domain(item.listing_domain)
    )
    final_type: Optional[ListingType] = data.listing_type
    if final_type is None:
        final_type = _parse_stored_listing_type(item.listing_type)
    if final_domain == ListingDomain.item and final_type is None:
        final_type = _infer_legacy_listing_type(item)

    final_price = data.price if data.price is not None else item.price

    val_adopt = data.adoption_details
    if val_adopt is None and item.adoption_details is not None:
        val_adopt = _adoption_create_from_orm(item.adoption_details)

    val_svc = data.service_details
    if val_svc is None and item.service_details is not None:
        val_svc = _service_details_create_from_orm(item.service_details)

    try:
        _validate_listing_business_rules(
            listing_domain=final_domain,
            listing_type=final_type,
            price=final_price,
            adoption_details=val_adopt,
            service_details=val_svc,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    exclude_fields = {"tag_names", "adoption_details", "service_details"}
    dump = data.model_dump(exclude_unset=True, exclude=exclude_fields)

    # Persist inferred listing_type when DB had NULL (fixes legacy rows on first save).
    if (
        final_domain == ListingDomain.item
        and item.listing_type is None
        and final_type is not None
        and "listing_type" not in dump
    ):
        item.listing_type = final_type.value

    for field_name, value in dump.items():
        if field_name == "listing_type" and value is None and final_domain == ListingDomain.item:
            continue
        if field_name == "status" and hasattr(value, "value"):
            value = value.value
        if field_name in ("listing_domain", "listing_type", "condition"):
            value = value.value if hasattr(value, "value") else value
        setattr(item, field_name, value)

    if item.is_public and (item.latitude is None or item.longitude is None):
        if owner.latitude is not None and owner.longitude is not None:
            item.latitude = owner.latitude
            item.longitude = owner.longitude
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Public listings require a location.",
            )

    # AI Enrichment on draft->public transition
    if was_private and will_be_public:
        from app.ai.enrichment import enrich_listing
        import logging
        log = logging.getLogger(__name__)
        
        try:
            # Get current adoption/service details
            service_cat = None
            animal_t = None
            
            if item.service_details:
                service_cat = item.service_details.service_category
            elif data.service_details:
                service_cat = data.service_details.service_category
                
            if item.adoption_details:
                animal_t = item.adoption_details.animal_type
            elif data.adoption_details:
                animal_t = data.adoption_details.animal_type
            
            result = enrich_listing(
                title=item.title,
                description=item.description,
                listing_domain=item.listing_domain,
                listing_type=item.listing_type,
                service_category=service_cat,
                animal_type=animal_t,
            )
            
            # Update with AI-assigned values (tags are not auto-applied)
            item.category = result.category
            item.subcategory = result.subcategory
            
            log.info(
                "AI enrichment on publish: item_id=%s category=%s subcategory=%s tags=%s confidence=%.2f",
                item.id, result.category, result.subcategory, result.tags, result.confidence
            )
        except Exception as e:
            log.warning("AI enrichment on publish failed (using current values): %s", e)
    
    if data.tag_names is not None:
        for link in list(item.item_tags):
            db.delete(link)
        for tag_name in data.tag_names:
            tag = get_or_create_tag(db, tag_name)
            db.add(ItemTag(item_id=item.id, tag_id=tag.id))

    if data.adoption_details is not None:
        _apply_adoption_details(db, item, data.adoption_details)

    if data.service_details is not None:
        _apply_service_details(db, item, data.service_details)

    db.commit()
    return get_item(db, item.id)


def delete_item(db: Session, item_id: int, owner: User) -> None:
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your item")
    db.delete(item)
    db.commit()


def build_seller_info(item: Item, requesting_user_id: Optional[int] = None) -> dict:
    """
    Build the seller info dict respecting privacy rules.
    Phone is only shown if: user has a phone AND show_phone_in_listing=True.
    """
    owner = item.owner
    phone = None
    if owner.phone_number and item.show_phone_in_listing:
        phone = owner.phone_number

    return {
        "id": owner.id,
        "username": owner.username,
        "display_name": owner.display_name,
        "city": owner.city,
        "phone_number": phone,
        "allow_messages": item.allow_messages,
    }


def _apply_text_search(q, query_str: str):
    """
    Filter a query by matching query_str across all searchable listing fields.

    Fields searched (in descending relevance order):
      title, category, subcategory, tags.name,
      service_details.service_category, adoption_details.animal_type, description
    """
    like = f"%{query_str}%"
    tag_match = sql_exists().where(
        ItemTag.item_id == Item.id,
        ItemTag.tag_id == Tag.id,
        Tag.name.ilike(like),
    )
    service_match = sql_exists().where(
        ServiceDetails.item_id == Item.id,
        ServiceDetails.service_category.ilike(like),
    )
    adoption_match = sql_exists().where(
        AdoptionDetails.item_id == Item.id,
        AdoptionDetails.animal_type.ilike(like),
    )
    return q.filter(
        or_(
            Item.title.ilike(like),
            Item.category.ilike(like),
            Item.subcategory.ilike(like),
            tag_match,
            service_match,
            adoption_match,
            Item.description.ilike(like),
        )
    )


def search_nearby_items(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: float,
    category: Optional[str] = None,
    query: Optional[str] = None,
    listing_domain: Optional[str] = None,
    listing_type: Optional[str] = None,
    service_category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: Optional[str] = None,
    *,
    page: int = 1,
    page_size: int = 20,
    text_search_mode: Optional[str] = None,
) -> tuple[List[dict], int]:
    settings = get_settings()
    tsm = (text_search_mode or "lexical").lower().strip()
    nq = normalize_free_text_for_embedding_query(query or "")

    def _radius_filtered_query(apply_query_text: bool):
        qq = (
            db.query(Item)
            .options(*_item_options())
            .filter(Item.is_public == True)
            .filter(Item.status.in_(DISCOVERABLE_STATUSES))
            .filter(Item.latitude.isnot(None))
            .filter(Item.longitude.isnot(None))
        )
        if category:
            qq = qq.filter(Item.category.ilike(f"%{category}%"))
        if query and apply_query_text:
            qq = _apply_text_search(qq, query)
        if listing_domain:
            qq = qq.filter(Item.listing_domain == listing_domain)
        if listing_type:
            qq = qq.filter(Item.listing_type == listing_type)
        if service_category:
            qq = qq.filter(Item.listing_domain == ListingDomain.service.value)
            qq = qq.filter(Item.service_category == service_category)
        if min_price is not None:
            qq = qq.filter(Item.price.isnot(None)).filter(Item.price >= min_price)
        if max_price is not None:
            qq = qq.filter(Item.price.isnot(None)).filter(Item.price <= max_price)
        min_lat, max_lat, min_lon, max_lon = approximate_lat_lon_bounds(latitude, longitude, radius_km)
        qq = qq.filter(Item.latitude >= min_lat, Item.latitude <= max_lat)
        if max_lon - min_lon < 340.0:
            qq = qq.filter(Item.longitude >= min_lon, Item.longitude <= max_lon)
        return qq

    items = _radius_filtered_query(True).all()
    if (
        tsm in ("hybrid", "semantic")
        and settings.enable_text_vector_search
        and nq
        and query
        and len(items) == 0
    ):
        items = _radius_filtered_query(False).all()

    cap = settings.search_radius_max_sql_candidates
    if len(items) > cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many listings match this area; try a smaller radius or tighter filters.",
        )

    pairs: List[Tuple[Item, float]] = []
    for item in items:
        dist = haversine_km(latitude, longitude, item.latitude, item.longitude)
        if dist <= radius_km:
            pairs.append((item, dist))

    vec_cap = settings.search_vector_candidate_cap
    if (
        tsm in ("hybrid", "semantic")
        and settings.enable_text_vector_search
        and nq
        and sort not in ("price_asc", "price_desc", "newest", "oldest", "nearest")
        and len(pairs) > vec_cap
    ):
        pairs.sort(key=lambda t: t[0].id)
        pairs = pairs[:vec_cap]

    results = []
    for item, dist in pairs:
        score, reason, breakdown = _calculate_ranking_score(item, dist, category, query)
        results.append({
            "item": item,
            "distance_km": round(dist, 2),
            "ranking_score": round(score, 4),
            "ranking_reason": reason,
            "ranking_breakdown": breakdown,
        })

    use_vector_rank = (
        tsm in ("hybrid", "semantic")
        and settings.enable_text_vector_search
        and bool(nq)
        and sort not in ("price_asc", "price_desc", "newest", "oldest", "nearest")
    )
    if use_vector_rank:
        from app.services.hybrid_search_service import maybe_apply_text_vector_ranking

        maybe_apply_text_vector_ranking(
            results,
            raw_query=query,
            text_search_mode=tsm,
            sort=sort,
            settings=settings,
        )

    if not use_vector_rank:
        if sort == "newest":
            results.sort(key=lambda x: x["item"].created_at, reverse=True)
        elif sort == "nearest":
            results.sort(key=lambda x: x["distance_km"])
        elif sort == "price_asc":
            results.sort(key=lambda x: (x["item"].price is None, x["item"].price or 0))
        elif sort == "price_desc":
            results.sort(key=lambda x: (x["item"].price is None, -(x["item"].price or 0)))
        elif sort == "oldest":
            results.sort(key=lambda x: x["item"].created_at)
        else:
            results.sort(key=lambda x: x["distance_km"])

    total_count = len(results)
    offset = (page - 1) * page_size
    return results[offset: offset + page_size], total_count


def search_by_bounds(
    db: Session,
    north: float,
    south: float,
    east: float,
    west: float,
    center_latitude: Optional[float] = None,
    center_longitude: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    condition: Optional[str] = None,
    query: Optional[str] = None,
    listing_domain: Optional[str] = None,
    listing_type: Optional[str] = None,
    service_category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: Optional[str] = None,
    *,
    page: int = 1,
    page_size: int = 100,
    text_search_mode: Optional[str] = None,
) -> tuple[List[dict], int]:
    settings = get_settings()
    tsm = (text_search_mode or "lexical").lower().strip()
    nq = normalize_free_text_for_embedding_query(query or "")

    def _bounds_query(apply_query_text: bool):
        qq = (
            db.query(Item)
            .options(*_item_options())
            .filter(Item.is_public == True)
            .filter(Item.status.in_(DISCOVERABLE_STATUSES))
            .filter(Item.latitude.isnot(None))
            .filter(Item.longitude.isnot(None))
            .filter(Item.latitude >= south)
            .filter(Item.latitude <= north)
        )
        if west <= east:
            qq = qq.filter(Item.longitude >= west).filter(Item.longitude <= east)
        else:
            qq = qq.filter((Item.longitude >= west) | (Item.longitude <= east))
        if category:
            qq = qq.filter(Item.category.ilike(f"%{category}%"))
        if subcategory:
            qq = qq.filter(Item.subcategory.ilike(f"%{subcategory}%"))
        if condition:
            qq = qq.filter(Item.condition == condition)
        if query and apply_query_text:
            qq = _apply_text_search(qq, query)
        if listing_domain:
            qq = qq.filter(Item.listing_domain == listing_domain)
        if listing_type:
            qq = qq.filter(Item.listing_type == listing_type)
        if service_category:
            qq = qq.filter(Item.listing_domain == ListingDomain.service.value)
            qq = qq.filter(Item.service_category == service_category)
        if min_price is not None:
            qq = qq.filter(Item.price.isnot(None)).filter(Item.price >= min_price)
        if max_price is not None:
            qq = qq.filter(Item.price.isnot(None)).filter(Item.price <= max_price)
        return qq

    items = _bounds_query(True).all()
    if (
        tsm in ("hybrid", "semantic")
        and settings.enable_text_vector_search
        and nq
        and query
        and len(items) == 0
    ):
        items = _bounds_query(False).all()

    cap = settings.search_bounds_max_sql_candidates
    if len(items) > cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many listings in this map area; zoom in or narrow filters.",
        )

    pre_rows: List[Tuple[Item, Optional[float]]] = []
    for item in items:
        dist = None
        if center_latitude is not None and center_longitude is not None:
            dist = haversine_km(center_latitude, center_longitude, item.latitude, item.longitude)
        pre_rows.append((item, dist))

    vec_cap = settings.search_vector_candidate_cap
    if (
        tsm in ("hybrid", "semantic")
        and settings.enable_text_vector_search
        and nq
        and sort not in ("price_asc", "price_desc", "newest", "oldest", "nearest")
        and len(pre_rows) > vec_cap
    ):
        pre_rows.sort(key=lambda t: t[0].id)
        pre_rows = pre_rows[:vec_cap]

    results = []
    for item, dist in pre_rows:
        score, reason, breakdown = _calculate_ranking_score(
            item, dist if dist is not None else 0.0, category, query
        )
        result = {
            "item": item,
            "ranking_score": round(score, 4),
            "ranking_reason": reason,
            "ranking_breakdown": breakdown,
        }
        if dist is not None:
            result["distance_km"] = round(dist, 2)
        results.append(result)

    def _bounds_dist_key(x: dict) -> tuple:
        d = x.get("distance_km")
        if d is not None:
            return (0, d)
        return (1, 0.0)

    use_vector_rank = (
        tsm in ("hybrid", "semantic")
        and settings.enable_text_vector_search
        and bool(nq)
        and sort not in ("price_asc", "price_desc", "newest", "oldest", "nearest")
    )
    if use_vector_rank:
        from app.services.hybrid_search_service import maybe_apply_text_vector_ranking

        maybe_apply_text_vector_ranking(
            results,
            raw_query=query,
            text_search_mode=tsm,
            sort=sort,
            settings=settings,
        )

    if not use_vector_rank:
        if sort == "newest":
            results.sort(key=lambda x: x["item"].created_at, reverse=True)
        elif sort == "nearest":
            results.sort(key=_bounds_dist_key)
        elif sort == "price_asc":
            results.sort(key=lambda x: (x["item"].price is None, x["item"].price or 0))
        elif sort == "price_desc":
            results.sort(key=lambda x: (x["item"].price is None, -(x["item"].price or 0)))
        elif sort == "oldest":
            results.sort(key=lambda x: x["item"].created_at)
        else:
            if center_latitude is not None and center_longitude is not None:
                results.sort(key=_bounds_dist_key)
            else:
                results.sort(key=lambda x: x["item"].created_at, reverse=True)

    total_count = len(results)
    offset = (page - 1) * page_size
    return results[offset: offset + page_size], total_count


def _calculate_ranking_score(
    item: Item,
    distance_km: float,
    search_category: Optional[str],
    search_query: Optional[str],
) -> tuple[float, str, dict]:
    distance_score = category_score = keyword_score = 0.0
    completeness_score = ai_confidence_score = fallback_penalty = 0.0
    factors = []

    if distance_km <= 1.0:
        distance_score = 50.0
    else:
        distance_score = 50.0 * (2.71828 ** (-0.2 * distance_km))
    factors.append(f"distance={distance_score:.1f}")

    if search_category:
        item_cat = (item.category or "").lower().strip()
        search_cat = search_category.lower().strip()
        if item_cat == search_cat:
            category_score = 20.0
            factors.append("exact_category=+20")
        elif search_cat in item_cat or item_cat in search_cat:
            category_score = 10.0
            factors.append("partial_category=+10")

    if search_query:
        q_lower = search_query.lower()
        title_lower = (item.title or "").lower()
        desc_lower = (item.description or "").lower()
        cat_lower = (item.category or "").lower()
        subcat_lower = (item.subcategory or "").lower()
        tag_names = [it.tag.name.lower() for it in (item.item_tags or []) if it.tag]
        service_cat = (
            item.service_details.service_category.lower()
            if item.service_details and item.service_details.service_category
            else ""
        )
        animal_type = (
            item.adoption_details.animal_type.lower()
            if item.adoption_details and item.adoption_details.animal_type
            else ""
        )
        if q_lower in title_lower:
            keyword_score += 15.0
            factors.append("keyword_in_title=+15")
        if q_lower in cat_lower or q_lower in subcat_lower:
            keyword_score += 10.0
            factors.append("keyword_in_category=+10")
        if any(q_lower in t for t in tag_names):
            keyword_score += 10.0
            factors.append("keyword_in_tags=+10")
        if service_cat and q_lower in service_cat:
            keyword_score += 8.0
            factors.append("keyword_in_service_cat=+8")
        if animal_type and q_lower in animal_type:
            keyword_score += 8.0
            factors.append("keyword_in_animal=+8")
        if q_lower in desc_lower:
            keyword_score += 5.0
            factors.append("keyword_in_desc=+5")

    if item.images:
        completeness_score += 4.0
    if item.description and len(item.description.strip()) > 20:
        completeness_score += 3.0
    if item.tags and len(item.tags) > 0:
        completeness_score += 3.0

    ai_analysis = item.latest_ai_analysis
    if ai_analysis:
        ai_confidence_score = ai_analysis.confidence * 5.0
    if ai_analysis and ai_analysis.used_fallback:
        fallback_penalty = -10.0

    total_score = max(
        distance_score + category_score + keyword_score
        + completeness_score + ai_confidence_score + fallback_penalty,
        0.0,
    )
    breakdown = {
        "distance_score": round(distance_score, 2),
        "category_score": round(category_score, 2),
        "keyword_score": round(keyword_score, 2),
        "completeness_score": round(completeness_score, 2),
        "ai_confidence_score": round(ai_confidence_score, 2),
        "fallback_penalty": round(fallback_penalty, 2),
        "total_score": round(total_score, 2),
    }
    return total_score, ", ".join(factors), breakdown


def add_image_to_item(
    db: Session,
    item_id: int,
    filename: str,
    url: str,
    is_primary: bool = False,
    owner: Optional[User] = None,
) -> ItemImage:
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if owner and item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your item")
    if is_primary:
        db.query(ItemImage).filter(
            ItemImage.item_id == item_id, ItemImage.is_primary == True
        ).update({"is_primary": False})
    image = ItemImage(item_id=item_id, filename=filename, url=url, is_primary=is_primary)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def delete_image_from_item(
    db: Session,
    item_id: int,
    image_id: int,
    owner: User,
) -> None:
    """
    Delete an image from a listing. Promotes the next image to primary if the
    deleted image was the primary. Removes the file via listing_media_storage.
    """
    from app.services.listing_media_storage import full_path_for_item_image

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your item")

    image = (
        db.query(ItemImage)
        .filter(ItemImage.id == image_id, ItemImage.item_id == item_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    was_primary = image.is_primary
    stored_filename = image.filename

    db.delete(image)
    db.flush()

    # Promote next remaining image to primary if necessary
    if was_primary:
        remaining = (
            db.query(ItemImage)
            .filter(ItemImage.item_id == item_id)
            .order_by(ItemImage.id)
            .first()
        )
        if remaining:
            remaining.is_primary = True

    db.commit()

    if stored_filename:
        try:
            file_path = full_path_for_item_image(item_id, stored_filename)
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass


def set_primary_image(
    db: Session,
    item_id: int,
    image_id: int,
    owner: User,
) -> ItemImage:
    """
    Set the primary (cover) image for a listing. Unsets any existing primary first.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your item")

    image = (
        db.query(ItemImage)
        .filter(ItemImage.id == image_id, ItemImage.item_id == item_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    db.query(ItemImage).filter(
        ItemImage.item_id == item_id, ItemImage.is_primary == True
    ).update({"is_primary": False})

    image.is_primary = True
    db.commit()
    db.refresh(image)
    return image


def save_ai_analysis(
    db: Session,
    item_id: int,
    image_id: int,
    result: AIAnalysisResult,
    classifier_output: Optional[AIClassificationOutput] = None,
    *,
    image_width: Optional[int] = None,
    image_height: Optional[int] = None,
    image_size_bytes: Optional[int] = None,
) -> ItemAIAnalysis:
    """
    Persist a row in ``item_ai_analyses`` (legacy schema).

    Active product scope: classification + tags only; ``title`` / ``description`` on
    ``AIAnalysisResult`` are not used for user-facing generation in current flows.
    Reserved for optional admin/debug tooling — not exposed as auto-fill for listings.
    """
    w = image_width if image_width is not None else (classifier_output.input_width if classifier_output else None)
    h = image_height if image_height is not None else (classifier_output.input_height if classifier_output else None)
    sz = image_size_bytes if image_size_bytes is not None else (classifier_output.input_file_size_bytes if classifier_output else None)
    analysis = ItemAIAnalysis(
        item_id=item_id,
        image_id=image_id,
        suggested_title=result.title,
        suggested_category=result.category,
        suggested_subcategory=result.subcategory,
        suggested_condition=result.condition,
        suggested_tags=result.smart_tags,
        suggested_description=result.description,
        confidence=result.confidence,
        ai_service=result.ai_service,
        category_confidence=result.category_confidence,
        subcategory_confidence=result.subcategory_confidence,
        used_fallback=result.used_fallback,
        image_width=w,
        image_height=h,
        image_size_bytes=sz,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def get_latest_ai_analysis(db: Session, item_id: int) -> Optional[ItemAIAnalysis]:
    return (
        db.query(ItemAIAnalysis)
        .filter(ItemAIAnalysis.item_id == item_id)
        .order_by(ItemAIAnalysis.created_at.desc())
        .first()
    )


def admin_set_listing_public(db: Session, item_id: int, *, is_public: bool) -> Item:
    """Moderation: show/hide listing. Caller commits (e.g. after audit log)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    item.is_public = is_public
    db.add(item)
    db.flush()
    db.refresh(item)
    return item


def admin_delete_listing(db: Session, item_id: int) -> None:
    """Hard delete listing. Caller commits (e.g. after audit log)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    db.delete(item)
    db.flush()


def admin_update_listing(db: Session, item_id: int, data: ItemUpdate) -> Item:
    """Apply ItemUpdate as the listing owner (moderation). Reuses update_item validation."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    owner = db.query(User).filter(User.id == item.user_id).first()
    if not owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Owner not found")
    return update_item(db, item_id, data, owner)


def admin_delete_image_from_item(
    db: Session,
    item_id: int,
    image_id: int,
    *,
    upload_dir=None,
) -> None:
    """Remove an image from a listing without ownership check (admin)."""
    from pathlib import Path

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    image = (
        db.query(ItemImage)
        .filter(ItemImage.id == image_id, ItemImage.item_id == item_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    was_primary = image.is_primary
    stored_filename = image.filename

    db.delete(image)
    db.flush()

    if was_primary:
        remaining = (
            db.query(ItemImage)
            .filter(ItemImage.item_id == item_id)
            .order_by(ItemImage.id)
            .first()
        )
        if remaining:
            remaining.is_primary = True

    db.commit()

    if upload_dir and stored_filename:
        try:
            file_path = Path(upload_dir) / str(item_id) / stored_filename
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass


def admin_set_primary_image(db: Session, item_id: int, image_id: int) -> ItemImage:
    """Set cover image without ownership check."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    image = (
        db.query(ItemImage)
        .filter(ItemImage.id == image_id, ItemImage.item_id == item_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    db.query(ItemImage).filter(
        ItemImage.item_id == item_id, ItemImage.is_primary == True
    ).update({"is_primary": False})

    image.is_primary = True
    db.commit()
    db.refresh(image)
    return image
