from __future__ import annotations

from dataclasses import dataclass

from sales_bot.services.admins import AdminService
from sales_bot.services.blacklist import BlacklistService
from sales_bot.services.delivery import DeliveryService
from sales_bot.services.oauth import RobloxOAuthService
from sales_bot.services.ownership import OwnershipService
from sales_bot.services.payments import PaymentService
from sales_bot.services.systems import SystemService
from sales_bot.services.vouches import VouchService


@dataclass(slots=True)
class ServiceContainer:
    admins: AdminService
    blacklist: BlacklistService
    systems: SystemService
    ownership: OwnershipService
    delivery: DeliveryService
    payments: PaymentService
    vouches: VouchService
    oauth: RobloxOAuthService
