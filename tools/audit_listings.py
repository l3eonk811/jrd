#!/usr/bin/env python3
"""
Classify `items` rows for data-quality review (read-only).

  cd backend && python -m tools.audit_listings

Uses DATABASE_URL from app settings (.env).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal


def main() -> None:
    db: Session = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT i.id, i.user_id, i.title, i.listing_domain, i.listing_type, i.price,
                       i.status, i.is_public, i.latitude, i.longitude,
                       EXISTS(SELECT 1 FROM adoption_details ad WHERE ad.item_id = i.id) AS has_adoption,
                       EXISTS(SELECT 1 FROM service_details sd WHERE sd.item_id = i.id) AS has_service
                FROM items i
                ORDER BY i.id
                """
            )
        ).fetchall()

        counts = {"VALID": 0, "PARTIAL": 0, "INCONSISTENT": 0, "BROKEN": 0}
        notes: list[str] = []

        for r in rows:
            (
                lid,
                _uid,
                title,
                dom,
                ltype,
                price,
                status,
                is_pub,
                lat,
                lon,
                has_adoption,
                has_service,
            ) = r
            issues: list[str] = []

            if title is None or not str(title).strip():
                issues.append("empty_title")

            if dom not in ("item", "service"):
                issues.append(f"bad_listing_domain:{dom!r}")

            if dom == "item":
                lt = (ltype or "").strip() if ltype else ""
                if not lt:
                    issues.append("missing_listing_type")
                elif lt not in ("sale", "donation", "adoption"):
                    issues.append(f"invalid_listing_type:{lt!r}")
                else:
                    if lt == "sale" and (price is None or float(price) <= 0):
                        issues.append("sale_requires_positive_price")
                    if lt in ("donation", "adoption") and price is not None:
                        issues.append("price_should_be_null")
                    if lt == "adoption" and not has_adoption:
                        issues.append("adoption_missing_adoption_details")

            if dom == "service":
                if ltype not in (None, ""):
                    issues.append("service_listing_type_should_be_null")
                if not has_service:
                    issues.append("service_missing_service_details")

            st = (status or "").strip()
            if st not in ("draft", "available", "reserved", "donated", "archived", "removed"):
                issues.append(f"unknown_status:{status!r}")

            if is_pub and st == "available" and (lat is None or lon is None):
                issues.append("discoverable_coords_missing")

            # Classify
            if "empty_title" in issues or "bad_listing_domain" in issues:
                bucket = "BROKEN"
            elif "service_missing_service_details" in issues or "adoption_missing_adoption_details" in issues:
                bucket = "BROKEN"
            elif "invalid_listing_type" in issues or "unknown_status" in issues:
                bucket = "INCONSISTENT"
            elif "missing_listing_type" in issues:
                bucket = "PARTIAL"
            elif issues:
                bucket = "INCONSISTENT"
            else:
                bucket = "VALID"

            counts[bucket] += 1
            if issues:
                notes.append(f"id={lid} [{bucket}] " + "; ".join(issues))

        print("=== items table audit ===")
        print(f"total: {len(rows)}")
        for k in ("VALID", "PARTIAL", "INCONSISTENT", "BROKEN"):
            print(f"  {k}: {counts[k]}")
        if notes:
            print("\n--- rows with issues (max 100) ---")
            for line in notes[:100]:
                print(line)
            if len(notes) > 100:
                print(f"... {len(notes) - 100} more")
    finally:
        db.close()


if __name__ == "__main__":
    main()
