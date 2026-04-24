from __future__ import annotations

from dataclasses import dataclass

from sales_bot.services.ai_assistant import AIAssistantService
from sales_bot.services.admins import AdminService
from sales_bot.services.blacklist import BlacklistService
from sales_bot.services.delivery import DeliveryService
from sales_bot.services.discounts import DiscountService
from sales_bot.services.engagement import EventService, GiveawayService, PollService
from sales_bot.services.oauth import RobloxOAuthService
from sales_bot.services.orders import OrderService
from sales_bot.services.ownership import OwnershipService
from sales_bot.services.panels import AdminPanelService
from sales_bot.services.payments import PaymentService
from sales_bot.services.roblox_creator import RobloxCreatorService
from sales_bot.services.special_systems import SpecialSystemService
from sales_bot.services.systems import SystemService
from sales_bot.services.vouches import VouchService
from sales_bot.services.web_auth import WebAuthService


@dataclass(slots=True)
class ServiceContainer:
    admins: AdminService
    blacklist: BlacklistService
    discounts: DiscountService
    systems: SystemService
    ownership: OwnershipService
    orders: OrderService
    delivery: DeliveryService
    payments: PaymentService
    vouches: VouchService
    oauth: RobloxOAuthService
    roblox_creator: RobloxCreatorService
    panels: AdminPanelService
    polls: PollService
    giveaways: GiveawayService
    events: EventService
    ai_assistant: AIAssistantService
    web_auth: WebAuthService
    special_systems: SpecialSystemService
