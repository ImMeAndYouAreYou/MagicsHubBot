from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SystemRecord:
    id: int
    name: str
    description: str
    file_path: str
    image_path: str | None
    paypal_link: str | None
    roblox_gamepass_id: str | None
    is_visible_on_website: bool
    is_for_sale: bool
    is_in_stock: bool
    website_price: str | None
    website_currency: str
    is_special_system: bool
    created_by: int | None
    created_at: str


@dataclass(slots=True, frozen=True)
class SystemAssetRecord:
    system_id: int
    asset_type: str
    asset_name: str
    asset_bytes: bytes
    updated_at: str


@dataclass(slots=True, frozen=True)
class SystemGalleryImageRecord:
    id: int
    system_id: int
    asset_name: str
    content_type: str | None
    asset_bytes: bytes
    sort_order: int
    created_at: str


@dataclass(slots=True, frozen=True)
class OwnedSystemRecord:
    system: SystemRecord
    source: str
    granted_by: int | None
    granted_at: str


@dataclass(slots=True, frozen=True)
class SavedSystemRecord:
    system: SystemRecord
    source: str
    saved_by: int | None
    saved_at: str


@dataclass(slots=True, frozen=True)
class BlacklistEntry:
    user_id: int
    display_label: str
    reason: str
    blacklisted_by: int | None
    blacklisted_at: str


@dataclass(slots=True, frozen=True)
class AppealRecord:
    id: int
    user_id: int
    answer_one: str
    answer_two: str
    owner_message_id: int | None
    status: str
    submitted_at: str
    reviewed_at: str | None
    reviewed_by: int | None


@dataclass(slots=True, frozen=True)
class PurchaseRecord:
    id: int
    user_id: int
    system_id: int
    status: str
    paypal_link: str
    created_at: str
    completed_at: str | None


@dataclass(slots=True, frozen=True)
class CartItemRecord:
    user_id: int
    system: SystemRecord
    added_at: str


@dataclass(slots=True, frozen=True)
class CheckoutOrderRecord:
    id: int
    user_id: int
    payment_method: str
    status: str
    paypal_status: str
    paypal_order_id: str | None
    paypal_capture_id: str | None
    paypal_approval_url: str | None
    paypal_payload_json: str | None
    discount_code_id: int | None
    discount_code_text: str | None
    subtotal_amount: str
    discount_amount: str
    total_amount: str
    currency: str
    note: str | None
    reviewed_at: str | None
    reviewed_by: int | None
    completed_at: str | None
    cancelled_at: str | None
    cancel_reason: str | None
    created_at: str


@dataclass(slots=True, frozen=True)
class CheckoutOrderItemRecord:
    order_id: int
    system_id: int
    system_name: str
    unit_price: str
    line_total: str


@dataclass(slots=True, frozen=True)
class DiscountCodeRecord:
    id: int
    code: str
    description: str | None
    discount_type: str
    amount: str
    currency: str | None
    system_id: int | None
    max_redemptions: int | None
    per_user_limit: int
    is_active: bool
    expires_at: str | None
    created_by: int | None
    created_at: str


@dataclass(slots=True, frozen=True)
class NotificationRecord:
    id: int
    user_id: int
    title: str
    body: str
    link_path: str | None
    kind: str
    is_read: bool
    created_by: int | None
    created_at: str
    read_at: str | None


@dataclass(slots=True, frozen=True)
class DeliveryRecord:
    id: int
    user_id: int
    system_id: int
    channel_id: int
    message_id: int
    source: str
    sent_at: str


@dataclass(slots=True, frozen=True)
class SystemDiscountRecord:
    user_id: int
    system: SystemRecord
    discount_percent: int
    created_by: int | None
    updated_by: int | None
    created_at: str
    updated_at: str


@dataclass(slots=True, frozen=True)
class VouchRecord:
    id: int
    admin_user_id: int
    author_user_id: int
    reason: str
    rating: int
    posted_message_id: int | None
    created_at: str


@dataclass(slots=True, frozen=True)
class VouchStats:
    total: int
    average_rating: float


@dataclass(slots=True, frozen=True)
class RobloxLinkRecord:
    user_id: int
    roblox_sub: str
    roblox_username: str | None
    roblox_display_name: str | None
    profile_url: str | None
    linked_at: str


@dataclass(slots=True, frozen=True)
class RobloxPublicProfile:
    user_id: int
    username: str
    display_name: str
    description: str
    created_at: str | None
    age_days: int | None
    headshot_url: str | None
    profile_url: str


@dataclass(slots=True, frozen=True)
class RobloxOwnerLinkRecord:
    guild_id: int
    discord_user_id: int
    roblox_sub: str
    roblox_username: str | None
    roblox_display_name: str | None
    profile_url: str | None
    token_type: str
    scope: str
    token_expires_at: str
    linked_at: str


@dataclass(slots=True, frozen=True)
class RobloxGamePassRecord:
    game_pass_id: int
    name: str
    description: str
    is_for_sale: bool
    icon_asset_id: int | None
    price_in_robux: int | None
    created_at: str
    updated_at: str


@dataclass(slots=True, frozen=True)
class SpecialSystemPaymentMethod:
    key: str
    label: str
    price: str


@dataclass(slots=True, frozen=True)
class SpecialSystemRecord:
    id: int
    slug: str
    title: str
    description: str
    payment_methods: tuple[SpecialSystemPaymentMethod, ...]
    channel_id: int
    message_id: int | None
    created_by: int | None
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(slots=True, frozen=True)
class SpecialSystemImageRecord:
    id: int
    special_system_id: int
    asset_name: str
    content_type: str | None
    asset_bytes: bytes
    sort_order: int
    created_at: str


@dataclass(slots=True, frozen=True)
class SpecialOrderRequestRecord:
    id: int
    special_system_id: int
    user_id: int
    discord_name: str
    roblox_name: str
    payment_method_key: str
    payment_method_label: str
    payment_price: str
    linked_roblox_sub: str | None
    linked_roblox_username: str | None
    linked_roblox_display_name: str | None
    status: str
    owner_message_id: int | None
    admin_reply: str | None
    submitted_at: str
    reviewed_at: str | None
    reviewed_by: int | None


@dataclass(slots=True, frozen=True)
class OrderRequestRecord:
    id: int
    user_id: int
    requested_item: str
    required_timeframe: str
    payment_method: str
    offered_price: str
    roblox_username: str | None
    status: str
    owner_message_id: int | None
    admin_reply: str | None
    submitted_at: str
    reviewed_at: str | None
    reviewed_by: int | None


@dataclass(slots=True, frozen=True)
class OrderRequestImageRecord:
    id: int
    order_id: int
    asset_name: str
    content_type: str | None
    asset_bytes: bytes
    sort_order: int
    created_at: str


@dataclass(slots=True, frozen=True)
class AdminPanelSessionRecord:
    token: str
    admin_user_id: int
    panel_type: str
    target_id: int | None
    expires_at: str
    created_at: str


@dataclass(slots=True, frozen=True)
class WebsiteSessionRecord:
    token: str
    discord_user_id: int
    username: str
    global_name: str | None
    avatar_hash: str | None
    expires_at: str
    created_at: str
    last_seen_at: str


@dataclass(slots=True, frozen=True)
class PollOption:
    emoji: str
    label: str


@dataclass(slots=True, frozen=True)
class PollRecord:
    id: int
    channel_id: int
    message_id: int | None
    question: str
    options: tuple[PollOption, ...]
    duration_value: int
    duration_unit: str
    ends_at: str
    status: str
    result_json: str | None
    created_by: int | None
    created_at: str
    updated_at: str
    closed_at: str | None


@dataclass(slots=True, frozen=True)
class GiveawayRecord:
    id: int
    channel_id: int
    message_id: int | None
    title: str
    description: str | None
    requirements: str | None
    winner_count: int
    duration_value: int
    duration_unit: str
    ends_at: str
    status: str
    result_json: str | None
    created_by: int | None
    created_at: str
    updated_at: str
    closed_at: str | None


@dataclass(slots=True, frozen=True)
class EventRecord:
    id: int
    channel_id: int
    message_id: int | None
    title: str
    description: str | None
    reward: str
    duration_value: int
    duration_unit: str
    ends_at: str
    status: str
    winner_user_id: int | None
    winner_message_id: int | None
    rolled_at: str | None
    created_by: int | None
    created_at: str
    updated_at: str
    closed_at: str | None


@dataclass(slots=True, frozen=True)
class AIKnowledgeRecord:
    id: int
    content: str
    created_by: int | None
    source_channel_id: int | None
    source_message_id: int | None
    created_at: str


@dataclass(slots=True, frozen=True)
class AITrainingStateRecord:
    is_active: bool
    started_by: int | None
    started_at: str | None
    ended_at: str | None
