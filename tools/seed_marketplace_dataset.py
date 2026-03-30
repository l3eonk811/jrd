#!/usr/bin/env python3
"""
Standalone marketplace seed for local/staging ONLY.

Creates fake users + listings in the real database (no frontend-only data).
Test marker: emails end with @marketplace.test.jrd

Usage (from repo root or backend):
  cd backend && python tools/seed_marketplace_dataset.py
  cd backend && python tools/seed_marketplace_dataset.py --extra-listings 150 --force

Safety:
  - Refuses to run if marketplace test users already exist unless --force
  - --force: deletes all users with @marketplace.test.jrd then seeds (CASCADE removes items)

Requires the backend Python environment (SQLAlchemy, etc.). If you use Docker and do not have a local venv:

  docker compose exec backend python tools/seed_marketplace_dataset.py --users 500 --extra-listings 120 --force

NOT for production.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Allow "python tools/seed_marketplace_dataset.py" from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("seed_marketplace")

from tools.seed_marketplace_content import (  # noqa: E402
    ADOPTION_SPECS,
    DONATION_SPECS,
    SALE_SPECS,
    SERVICE_CAT_KEYS,
    display_name_for_index,
    service_title_and_description,
)

# --- Identifiers ---
TEST_EMAIL_DOMAIN = "marketplace.test.jrd"
SEED_PASSWORD_PLAIN = "MarketTest2026!"  # meets typical min length; change in staging if policy differs

# --- Riyadh envelope + zones (reporting labels only; not DB columns) ---
RIYADH_BOUNDS = {
    "min_lat": 24.42,
    "max_lat": 24.92,
    "min_lon": 46.48,
    "max_lon": 46.92,
}

RIYADH_ZONES = [
    {"id": "north", "label_en": "North Riyadh", "min_lat": 24.76, "max_lat": 24.90, "min_lon": 46.54, "max_lon": 46.82},
    {"id": "south", "label_en": "South Riyadh", "min_lat": 24.48, "max_lat": 24.62, "min_lon": 46.56, "max_lon": 46.84},
    {"id": "east", "label_en": "East Riyadh", "min_lat": 24.56, "max_lat": 24.80, "min_lon": 46.74, "max_lon": 46.90},
    {"id": "west", "label_en": "West Riyadh", "min_lat": 24.56, "max_lat": 24.80, "min_lon": 46.48, "max_lon": 46.66},
    {"id": "central", "label_en": "Central Riyadh", "min_lat": 24.63, "max_lat": 24.76, "min_lon": 46.62, "max_lon": 46.76},
]

_JITTER = 0.004
_LISTING_EXTRA_JITTER = 0.01


def clamp_to_riyadh(lat: float, lon: float) -> tuple[float, float]:
    b = RIYADH_BOUNDS
    return max(b["min_lat"], min(b["max_lat"], lat)), max(b["min_lon"], min(b["max_lon"], lon))


def random_point_in_zone(zone: dict, rng: random.Random) -> tuple[float, float, str]:
    lat = rng.uniform(zone["min_lat"], zone["max_lat"]) + rng.uniform(-_JITTER, _JITTER)
    lon = rng.uniform(zone["min_lon"], zone["max_lon"]) + rng.uniform(-_JITTER, _JITTER)
    lat, lon = clamp_to_riyadh(lat, lon)
    return round(lat, 6), round(lon, 6), zone["id"]


def allocate_zone_queue(n: int, rng: random.Random) -> list[dict]:
    per = [n // 5] * 5
    for i in range(n % 5):
        per[i] += 1
    q: list[dict] = []
    for zi, c in enumerate(per):
        q.extend([RIYADH_ZONES[zi]] * c)
    rng.shuffle(q)
    return q


def build_kind_queue(n_users: int, rng: random.Random) -> list[str]:
    """Balanced primary listing kinds: sale, donation, adoption, service."""
    # 175 / 75 / 75 / 175 = 500
    kinds = (
        ["sale"] * 175
        + ["donation"] * 75
        + ["adoption"] * 75
        + ["service"] * 175
    )
    assert len(kinds) == n_users
    rng.shuffle(kinds)
    return kinds


def pick_sale_spec(i: int, rng: random.Random) -> dict:
    base = SALE_SPECS[i % len(SALE_SPECS)]
    spec = dict(base)
    spec["title"] = f"{base['title']} · #{i+1:04d}"
    return spec


def pick_donation_spec(i: int, rng: random.Random) -> dict:
    base = DONATION_SPECS[i % len(DONATION_SPECS)]
    spec = dict(base)
    spec["title"] = f"{base['title']} (#{i+1})"
    return spec


def pick_adoption_spec(i: int, rng: random.Random) -> dict:
    base = ADOPTION_SPECS[i % len(ADOPTION_SPECS)]
    return dict(base)


def pick_service_spec(i: int, rng: random.Random) -> tuple[str, str, str]:
    cat = SERVICE_CAT_KEYS[i % len(SERVICE_CAT_KEYS)]
    title, desc = service_title_and_description(cat)
    title = f"{title} · حي قريب #{i+1:04d}"
    return cat, title, desc


def saudi_mobile(rng: random.Random) -> str:
    return "+9665" + "".join(str(rng.randint(0, 9)) for _ in range(8))


@dataclass
class SeedStats:
    users: int = 0
    listings: int = 0
    by_listing_type: Counter = field(default_factory=Counter)
    by_category: Counter = field(default_factory=Counter)
    by_service_category: Counter = field(default_factory=Counter)
    by_zone: Counter = field(default_factory=Counter)
    lats: list[float] = field(default_factory=list)
    lons: list[float] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)


def write_markdown_report(
    path: Path,
    stats: SeedStats,
    assumptions: list[str],
    run_cmd: str,
) -> None:
    lines = [
        "# Seeded test data report",
        "",
        "**Scope:** local/staging testing only. Do not run against production.",
        "",
        "- **Generator:** `backend/tools/seed_marketplace_dataset.py`",
        "- **Templates:** `backend/tools/seed_marketplace_content.py`",
        "- **Test marker:** emails end with `@marketplace.test.jrd`",
        "- **Idempotency:** not idempotent; re-run requires `--force` (deletes prior test users) or `--purge` first.",
        "",
        f"Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total users | {stats.users} |",
        f"| Total listings | {stats.listings} |",
        f"| Latitude min / max | {min(stats.lats) if stats.lats else 'n/a'} / {max(stats.lats) if stats.lats else 'n/a'} |",
        f"| Longitude min / max | {min(stats.lons) if stats.lons else 'n/a'} / {max(stats.lons) if stats.lons else 'n/a'} |",
        "",
        "## Breakdown by listing type (`listing_type` or `service`)",
        "",
    ]
    for k, v in sorted(stats.by_listing_type.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## Breakdown by `Item.category` (major category string)", ""]
    for k, v in sorted(stats.by_category.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## Service listings by `service_category` key", ""]
    for k, v in sorted(stats.by_service_category.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## Geographic breakdown (Riyadh zones, generation-time labels)", ""]
    for k, v in sorted(stats.by_zone.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- **{k}**: {v}")
    lines += [
        "",
        "## Example sample records",
        "",
    ]
    for i, s in enumerate(stats.samples[:6], 1):
        lines.append(f"### Sample {i}")
        lines.append("```json")
        lines.append(json.dumps(s, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    lines += [
        "## Assumptions",
        "",
    ]
    for a in assumptions:
        lines.append(f"- {a}")
    lines += [
        "",
        "## How to run safely (local / staging only)",
        "",
        "```bash",
        run_cmd,
        "```",
        "",
        "- Use a **staging** database or local Docker Postgres, never production.",
        "- Test accounts use email `*@marketplace.test.jrd` and shared password documented in script output.",
        "- Script is **not idempotent** unless you use `--force` (which deletes prior test users first).",
        "",
        "## Cleanup",
        "",
        "```bash",
        "cd backend && python tools/seed_marketplace_dataset.py --purge",
        "```",
        "",
        "Deletes all users with emails ending in `@marketplace.test.jrd` (items CASCADE).",
        "",
        "## Password",
        "",
        "The shared test password is printed once in the console after a successful seed (not stored in this file).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote report: %s", path)


def run_seed(
    num_users: int,
    extra_listings: int,
    force: bool,
    report_path: Path,
) -> None:
    from app.database import SessionLocal
    from app.models import User, Tag, ItemTag
    from app.models.item import (
        Item,
        ItemStatus,
        ListingDomain,
        AdoptionDetails,
        ServiceDetails,
        PricingModel,
        ServiceMode,
    )
    from app.services.auth_service import hash_password, PasswordError

    rng = random.Random(2026)

    db = SessionLocal()
    stats = SeedStats()
    assumptions = [
        "Users and items inserted via SQLAlchemy ORM consistent with existing models.",
        "Discover visibility: `is_public=True`, `status=available`, coordinates inside Riyadh envelope.",
        "Service listings set `Item.service_category` and `ServiceDetails.service_category` to canonical keys.",
        "Currency `SAR` on all items per non-null column default.",
        "No listing images attached (optional); Discover works without images.",
        "Mixed Arabic/English display names; emails are unique under @marketplace.test.jrd.",
    ]

    try:
        existing = (
            db.query(User).filter(User.email.like(f"%@{TEST_EMAIL_DOMAIN}")).count()
        )
        if existing and not force:
            log.error(
                "Found %d existing users with @%s — aborting. Use --force to purge and re-seed.",
                existing,
                TEST_EMAIL_DOMAIN,
            )
            sys.exit(2)

        if existing and force:
            log.warning("Removing %d existing marketplace test users (CASCADE)...", existing)
            olds = db.query(User).filter(User.email.like(f"%@{TEST_EMAIL_DOMAIN}")).all()
            for u in olds:
                db.delete(u)
            db.commit()

        try:
            hashed = hash_password(SEED_PASSWORD_PLAIN)
        except PasswordError as e:
            log.error("Password rejected by validator: %s", e)
            sys.exit(1)

        zone_queue = allocate_zone_queue(num_users, rng)
        kind_queue = build_kind_queue(num_users, rng)

        # Counters for rotating specs
        sale_rot, don_rot, adop_rot = 0, 0, 0

        created_users: list[tuple[User, str, float, float]] = []

        for i in range(num_users):
            zone = zone_queue[i]
            lat_u, lon_u, zid = random_point_in_zone(zone, rng)
            email = f"mkt_{i+1:05d}@{TEST_EMAIL_DOMAIN}"
            username = f"mkt_u{i+1:05d}"
            display = display_name_for_index(i)
            phone = saudi_mobile(rng)

            user = User(
                email=email,
                username=username,
                hashed_password=hashed,
                display_name=display,
                phone_number=phone,
                city="Riyadh",
                latitude=lat_u,
                longitude=lon_u,
                is_active=True,
                is_blocked=False,
                is_email_verified=True,
                is_admin=False,
                role="viewer",
                allow_messages_default=True,
                allow_phone_default=False,
            )
            db.add(user)
            db.flush()
            created_users.append((user, zid, lat_u, lon_u))

            kind = kind_queue[i]
            # listing coords near user
            lat_i = lat_u + rng.uniform(-_LISTING_EXTRA_JITTER, _LISTING_EXTRA_JITTER)
            lon_i = lon_u + rng.uniform(-_LISTING_EXTRA_JITTER, _LISTING_EXTRA_JITTER)
            lat_i, lon_i = clamp_to_riyadh(lat_i, lon_i)
            lat_i, lon_i = round(lat_i, 6), round(lon_i, 6)

            tags: list[str] = []
            if kind == "sale":
                spec = pick_sale_spec(sale_rot, rng)
                sale_rot += 1
                price = float(rng.randint(spec["price"][0] // 50, spec["price"][1] // 50) * 50)
                item = Item(
                    user_id=user.id,
                    title=spec["title"][:250],
                    description=spec["description"],
                    category=spec["category"],
                    condition=spec["condition"],
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.item.value,
                    listing_type="sale",
                    price=price,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=bool(rng.randint(0, 1)),
                )
                tags = ["للبيع", spec["category"], "الرياض"]
                stats.by_listing_type["sale"] += 1
                stats.by_category[spec["category"]] += 1
            elif kind == "donation":
                spec = pick_donation_spec(don_rot, rng)
                don_rot += 1
                item = Item(
                    user_id=user.id,
                    title=spec["title"][:250],
                    description=spec["description"],
                    category=spec["category"],
                    condition="good",
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.item.value,
                    listing_type="donation",
                    price=None,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=False,
                )
                tags = ["تبرع", "مجاني", "الرياض"]
                stats.by_listing_type["donation"] += 1
                stats.by_category[spec["category"]] += 1
            elif kind == "adoption":
                spec = pick_adoption_spec(adop_rot, rng)
                adop_rot += 1
                item = Item(
                    user_id=user.id,
                    title=spec["title"][:250],
                    description=spec["description"],
                    category=spec["category"],
                    condition=None,
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.item.value,
                    listing_type="adoption",
                    price=None,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=False,
                )
                tags = ["تبني", spec["animal_type"], "الرياض"]
                stats.by_listing_type["adoption"] += 1
                stats.by_category[spec["category"]] += 1
                db.add(item)
                db.flush()
                db.add(
                    AdoptionDetails(
                        item_id=item.id,
                        animal_type=spec["animal_type"],
                        age=rng.choice(["3 أشهر", "سنة", "سنتان", "غير محدد"]),
                        gender=spec.get("gender", "unknown"),
                        health_status="يبدو بصحة جيدة؛ المعاينة البيطرية على المكلف",
                        vaccinated_status=spec.get("vaccinated_status", "unknown"),
                        neutered_status=rng.choice(["unknown", "neutered", "not_neutered"]),
                        adoption_reason="ظروف منزلية أو سفر — أبحث عن بيت دائم",
                        special_experience_required=rng.choice([True, False]),
                    )
                )
                _add_tags(db, item.id, tags)
                stats.listings += 1
                stats.by_zone[zid] += 1
                stats.lats.append(lat_i)
                stats.lons.append(lon_i)
                if len(stats.samples) < 8:
                    stats.samples.append(
                        {
                            "user_email": email,
                            "listing_title": item.title,
                            "kind": "adoption",
                            "zone": zid,
                            "lat": lat_i,
                            "lon": lon_i,
                        }
                    )
                continue
            else:  # service
                cat_key, title, desc = pick_service_spec(i, rng)
                item = Item(
                    user_id=user.id,
                    title=title[:250],
                    description=desc,
                    category="Services",
                    condition=None,
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.service.value,
                    listing_type=None,
                    service_category=cat_key,
                    price=None,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=True,
                )
                tags = ["خدمات", cat_key, "الرياض"]
                stats.by_listing_type["service"] += 1
                stats.by_category["Services"] += 1
                stats.by_service_category[cat_key] += 1
                db.add(item)
                db.flush()
                db.add(
                    ServiceDetails(
                        item_id=item.id,
                        service_category=cat_key,
                        pricing_model=rng.choice(
                            [PricingModel.hourly.value, PricingModel.fixed.value, PricingModel.negotiable.value]
                        ),
                        service_mode=rng.choice(
                            [
                                ServiceMode.at_client_location.value,
                                ServiceMode.at_provider_location.value,
                                ServiceMode.remote.value,
                            ]
                        ),
                        service_area="داخل نطاق الرياض — التفاصيل بالاتفاق",
                        availability_notes=rng.choice(
                            [
                                "أفضّل المساء وأيام الخميس–الجمعة",
                                "التواصل واتساب أولاً",
                                "مواعيد مرنة حسب الأسبوع",
                            ]
                        ),
                        experience_years=rng.randint(1, 15),
                    )
                )
                _add_tags(db, item.id, tags)
                stats.listings += 1
                stats.by_zone[zid] += 1
                stats.lats.append(lat_i)
                stats.lons.append(lon_i)
                if len(stats.samples) < 8:
                    stats.samples.append(
                        {
                            "user_email": email,
                            "listing_title": item.title,
                            "kind": "service",
                            "service_category": cat_key,
                            "zone": zid,
                            "lat": lat_i,
                            "lon": lon_i,
                        }
                    )
                continue

            # sale / donation only (adoption/service handled above with continue)
            db.add(item)
            db.flush()
            _add_tags(db, item.id, tags)
            stats.listings += 1
            stats.by_zone[zid] += 1
            stats.lats.append(lat_i)
            stats.lons.append(lon_i)
            if len(stats.samples) < 8:
                stats.samples.append(
                    {
                        "user_email": email,
                        "listing_title": item.title,
                        "kind": kind,
                        "zone": zid,
                        "lat": lat_i,
                        "lon": lon_i,
                    }
                )

        # --- Extra listings (some users get 2+) ---
        extra_sale = extra_listings // 4
        extra_don = extra_listings // 4
        extra_adop = extra_listings // 4
        extra_svc = extra_listings - extra_sale - extra_don - extra_adop
        extra_kinds = (
            ["sale"] * extra_sale
            + ["donation"] * extra_don
            + ["adoption"] * extra_adop
            + ["service"] * extra_svc
        )
        rng.shuffle(extra_kinds)

        for j, ek in enumerate(extra_kinds):
            user, zid, lat_u, lon_u = rng.choice(created_users)
            lat_i = lat_u + rng.uniform(-_LISTING_EXTRA_JITTER * 2, _LISTING_EXTRA_JITTER * 2)
            lon_i = lon_u + rng.uniform(-_LISTING_EXTRA_JITTER * 2, _LISTING_EXTRA_JITTER * 2)
            lat_i, lon_i = clamp_to_riyadh(lat_i, lon_i)
            lat_i, lon_i = round(lat_i, 6), round(lon_i, 6)

            if ek == "sale":
                spec = pick_sale_spec(sale_rot + j, rng)
                price = float(rng.randint(spec["price"][0] // 50, spec["price"][1] // 50) * 50)
                item = Item(
                    user_id=user.id,
                    title=("إضافي · " + spec["title"])[:250],
                    description=spec["description"],
                    category=spec["category"],
                    condition=spec["condition"],
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.item.value,
                    listing_type="sale",
                    price=price,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=False,
                )
                db.add(item)
                db.flush()
                _add_tags(db, item.id, ["للبيع", "إضافي", "الرياض"])
                stats.by_listing_type["sale"] += 1
                stats.by_category[spec["category"]] += 1
            elif ek == "donation":
                spec = pick_donation_spec(don_rot + j, rng)
                item = Item(
                    user_id=user.id,
                    title=("إضافي · " + spec["title"])[:250],
                    description=spec["description"],
                    category=spec["category"],
                    condition="good",
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.item.value,
                    listing_type="donation",
                    price=None,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=False,
                )
                db.add(item)
                db.flush()
                _add_tags(db, item.id, ["تبرع", "إضافي"])
                stats.by_listing_type["donation"] += 1
                stats.by_category[spec["category"]] += 1
            elif ek == "adoption":
                spec = pick_adoption_spec(adop_rot + j, rng)
                item = Item(
                    user_id=user.id,
                    title=("إضافي · " + spec["title"])[:250],
                    description=spec["description"],
                    category=spec["category"],
                    condition=None,
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.item.value,
                    listing_type="adoption",
                    price=None,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=False,
                )
                db.add(item)
                db.flush()
                db.add(
                    AdoptionDetails(
                        item_id=item.id,
                        animal_type=spec["animal_type"],
                        age=rng.choice(["4 أشهر", "سنة"]),
                        gender=spec.get("gender", "unknown"),
                        vaccinated_status=spec.get("vaccinated_status", "unknown"),
                        special_experience_required=False,
                    )
                )
                _add_tags(db, item.id, ["تبني", "إضافي"])
                stats.by_listing_type["adoption"] += 1
                stats.by_category[spec["category"]] += 1
            else:
                cat_key, title, desc = pick_service_spec(stats.listings + j, rng)
                item = Item(
                    user_id=user.id,
                    title=("خدمة إضافية · " + title)[:250],
                    description=desc,
                    category="Services",
                    condition=None,
                    status=ItemStatus.available.value,
                    is_public=True,
                    latitude=lat_i,
                    longitude=lon_i,
                    listing_domain=ListingDomain.service.value,
                    listing_type=None,
                    service_category=cat_key,
                    price=None,
                    currency="SAR",
                    allow_messages=True,
                    show_phone_in_listing=True,
                )
                db.add(item)
                db.flush()
                db.add(
                    ServiceDetails(
                        item_id=item.id,
                        service_category=cat_key,
                        pricing_model=PricingModel.negotiable.value,
                        service_mode=ServiceMode.at_client_location.value,
                        service_area="الرياض",
                        experience_years=rng.randint(2, 12),
                    )
                )
                _add_tags(db, item.id, ["خدمات", cat_key])
                stats.by_listing_type["service"] += 1
                stats.by_category["Services"] += 1
                stats.by_service_category[cat_key] += 1

            stats.listings += 1
            stats.by_zone[zid] += 1
            stats.lats.append(lat_i)
            stats.lons.append(lon_i)

        stats.users = num_users
        db.commit()
        log.info("Committed: %d users, %d listings.", stats.users, stats.listings)
        log.info("Shared test password: %s", SEED_PASSWORD_PLAIN)
        log.info("Example login: mkt_00001@%s", TEST_EMAIL_DOMAIN)

        run_cmd = f"cd backend && python tools/seed_marketplace_dataset.py --users {num_users} --extra-listings {extra_listings} --force"
        write_markdown_report(report_path, stats, assumptions, run_cmd)

    except Exception as e:
        log.exception("Seed failed: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


def _add_tags(db, item_id: int, tags: list[str]) -> None:
    from app.models import Tag, ItemTag

    for tag_name in tags:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name[:80])
            db.add(tag)
            db.flush()
        db.add(ItemTag(item_id=item_id, tag_id=tag.id))


def purge_marketplace_users() -> int:
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        q = db.query(User).filter(User.email.like(f"%@{TEST_EMAIL_DOMAIN}")).all()
        n = len(q)
        for u in q:
            db.delete(u)
        db.commit()
        return n
    finally:
        db.close()


def default_report_path() -> Path:
    """Repo root report when running from a full clone; `backend/` only when only `/app` is mounted (Docker)."""
    backend = Path(__file__).resolve().parents[1]
    compose = backend.parent / "docker-compose.yml"
    if compose.is_file():
        return backend.parent / "SEEDED_TEST_DATA_REPORT.md"
    return backend / "SEEDED_TEST_DATA_REPORT.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed marketplace test dataset (local/staging)")
    parser.add_argument("--users", type=int, default=500, help="Number of users (default 500)")
    parser.add_argument(
        "--extra-listings",
        type=int,
        default=120,
        help="Additional listings beyond one-per-user (default 120, approx 620 total with 500 users)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing @marketplace.test.jrd users first",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Only delete marketplace test users and exit",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="",
        help="Path to Markdown report (default: repo root SEEDED_TEST_DATA_REPORT.md)",
    )
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else default_report_path()

    if args.purge:
        n = purge_marketplace_users()
        log.info("Purged %d marketplace test users.", n)
        return

    run_seed(args.users, args.extra_listings, args.force, report_path)


if __name__ == "__main__":
    main()
