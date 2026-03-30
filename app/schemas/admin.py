from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AdminUserRow(BaseModel):
    id: int
    name: Optional[str] = None
    username: str
    phone: Optional[str] = None
    created_at: datetime
    is_active: bool
    is_blocked: bool
    is_admin: bool = False
    role: str
    listings_count: int


class AdminUserListResponse(BaseModel):
    items: List[AdminUserRow]
    total: int
    page: int
    page_size: int


class AdminListingBrief(BaseModel):
    id: int
    title: str
    listing_domain: str
    status: str
    is_public: bool
    created_at: datetime


class AdminProviderRatingSummary(BaseModel):
    average_rating: float
    rating_count: int


class AdminUserDetail(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    username: str
    phone: Optional[str] = None
    created_at: datetime
    is_active: bool
    is_blocked: bool
    is_admin: bool
    role: str
    listings_count: int
    reports_count: int
    provider_rating_summary: Optional[AdminProviderRatingSummary] = None
    recent_listings: List[AdminListingBrief]


class AdminUserFlagResponse(BaseModel):
    ok: bool = True
    user_id: int
    is_blocked: bool


class AdminMeResponse(BaseModel):
    id: int
    email: str
    username: str
    role: str


class AdminUserRolePatch(BaseModel):
    role: str


class AdminUserStaffPatch(BaseModel):
    """Promote/demote admin access and set console role (super_admin only)."""

    is_admin: bool
    role: Optional[str] = None


class AdminListingOwnerBrief(BaseModel):
    id: int
    name: Optional[str] = None
    username: str


class AdminListingRow(BaseModel):
    id: int
    title: str
    listing_domain: str
    listing_type: Optional[str] = None
    owner: AdminListingOwnerBrief
    status: str
    is_hidden: bool
    created_at: datetime
    reports_count: int


class AdminListingListResponse(BaseModel):
    items: List[AdminListingRow]
    total: int
    page: int
    page_size: int


class AdminListingImageBrief(BaseModel):
    id: int
    url: str
    is_primary: bool


class AdminListingDetail(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    listing_domain: str
    listing_type: Optional[str] = None
    owner: AdminListingOwnerBrief
    status: str
    is_hidden: bool
    created_at: datetime
    reports_count: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    show_phone_in_listing: bool = False
    allow_messages: bool = True
    images: List["AdminListingImageBrief"] = []


class AdminListingOkResponse(BaseModel):
    ok: bool = True
    listing_id: int
    is_hidden: bool


class AdminAuditRow(BaseModel):
    id: int
    admin_user_id: Optional[int] = None
    admin_display_name: Optional[str] = None
    admin_username: Optional[str] = None
    action: str
    target_type: str
    target_id: int
    details: Optional[str] = None
    created_at: datetime


class AdminAuditListResponse(BaseModel):
    items: List[AdminAuditRow]
    total: int
    page: int
    page_size: int


class AdminReportReporterBrief(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None


class AdminReportRow(BaseModel):
    id: int
    reporter: AdminReportReporterBrief
    target_type: str
    target_id: int
    reason: str
    note: Optional[str] = None
    status: str
    created_at: datetime


class AdminReportListResponse(BaseModel):
    items: List[AdminReportRow]
    total: int
    page: int
    page_size: int


class AdminReportStatusResponse(BaseModel):
    ok: bool = True
    id: int
    status: str


class AdminSettingRow(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: datetime


class AdminSettingListResponse(BaseModel):
    items: List[AdminSettingRow]


class AdminSettingPatch(BaseModel):
    value: str


# ── Providers (service listings directory) ───────────────────────────────────


class AdminProviderRow(BaseModel):
    user_id: int
    username: str
    display_name: Optional[str] = None
    city: Optional[str] = None
    active_service_listings: int
    average_rating: Optional[float] = None
    rating_count: int = 0


class AdminProviderListResponse(BaseModel):
    items: List[AdminProviderRow]
    total: int
    page: int
    page_size: int


# ── Provider ratings (reviews) ────────────────────────────────────────────────


class AdminProviderRatingRow(BaseModel):
    id: int
    provider_user_id: int
    provider_username: str
    rater_user_id: int
    rater_username: str
    stars: int
    comment: Optional[str] = None
    created_at: datetime


class AdminProviderRatingListResponse(BaseModel):
    items: List[AdminProviderRatingRow]
    total: int
    page: int
    page_size: int


# ── Conversations (admin read-only) ───────────────────────────────────────────


class AdminConversationParticipantBrief(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None


class AdminConversationSummary(BaseModel):
    id: int
    item_id: int
    item_title: Optional[str] = None
    owner: AdminConversationParticipantBrief
    interested: AdminConversationParticipantBrief
    last_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    you_blocked_them: bool = False
    they_blocked_you: bool = False


class AdminConversationListResponse(BaseModel):
    items: List[AdminConversationSummary]
    total: int
    page: int
    page_size: int


class AdminStatsTotals(BaseModel):
    total_users: int
    total_listings: int
    total_conversations: int
    total_blocked_users: int
    total_pending_reports: int


class CityCount(BaseModel):
    city: str
    count: int


class AdminStatsActivity(BaseModel):
    """Activity metrics for the selected time window (UTC)."""

    time_range: str = Field(..., description="Echo of query param range: day | 7d | month | year")
    period_start: datetime
    period_end: datetime
    new_users: int
    new_listings: int
    published_listings: int
    hidden_listings: int
    archived_listings: int
    reports_created: int
    reports_by_status: Dict[str, int]
    conversations_created: int
    messages_sent: int
    admin_actions_count: int
    listings_by_type: Dict[str, int]
    listings_by_city: List[CityCount]


class AdminStatsResponse(BaseModel):
    totals: AdminStatsTotals
    activity: AdminStatsActivity


class AdminMessageRow(BaseModel):
    id: int
    sender_user_id: int
    sender_username: Optional[str] = None
    body: str
    message_kind: str = "text"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    read_at: Optional[datetime] = None


class AdminConversationDetail(BaseModel):
    id: int
    item_id: int
    item_title: Optional[str] = None
    listing_domain: Optional[str] = None
    listing_type: Optional[str] = None
    owner: AdminConversationParticipantBrief
    interested: AdminConversationParticipantBrief
    messages: List[AdminMessageRow] = []
    you_blocked_them: bool = False
    they_blocked_you: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None
