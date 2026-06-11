"""Pacote de models.

Importa todos os módulos para que TODAS as classes sejam registradas no mesmo
`registry` (via `Base`) antes de qualquer configuração de mapper. É isso que
permite os `relationship()` resolverem classes-alvo entre módulos por nome.
"""

from __future__ import annotations

from .base import Base
from .enums import (
    AppointmentStatus,
    ConsentStatus,
    ContactChannel,
    DeliveryStatus,
    IntegrationProvider,
    IntegrationStatus,
    LoyaltyCategoria,
    LoyaltyNivel,
    LoyaltyStatus,
    MessageDirection,
    PaymentMethod,
    ServiceCategory,
    SubscriptionStatus,
    SyncStatus,
    UnitRole,
)
from .organization import Organization, Plan, Subscription
from .unit import BusinessHours, Unit
from .user import User, UserUnit
from .barber import Barber, BarberService, BarberUnit, TimeOff
from .client import Client, ClientConsent
from .service import Service
from .appointment import Appointment, AppointmentItem
from .payment import Expense, ExpenseCategory, Payment
from .integration import CalendarSync, IntegrationAccount, MessageLog
from .loyalty import ClientLoyalty

__all__ = [
    "Base",
    # enums
    "AppointmentStatus",
    "ConsentStatus",
    "ContactChannel",
    "DeliveryStatus",
    "IntegrationProvider",
    "IntegrationStatus",
    "MessageDirection",
    "PaymentMethod",
    "ServiceCategory",
    "SubscriptionStatus",
    "SyncStatus",
    "UnitRole",
    # tenant
    "Organization",
    "Plan",
    "Subscription",
    # estrutura
    "Unit",
    "BusinessHours",
    "User",
    "UserUnit",
    "Barber",
    "BarberService",
    "BarberUnit",
    "TimeOff",
    # clientes
    "Client",
    "ClientConsent",
    # serviços
    "Service",
    "BarberService",
    # agenda
    "Appointment",
    "AppointmentItem",
    # financeiro
    "Payment",
    "ExpenseCategory",
    "Expense",
    # integrações
    "IntegrationAccount",
    "CalendarSync",
    "MessageLog",
    # fidelidade
    "ClientLoyalty",
    "LoyaltyNivel",
    "LoyaltyStatus",
    "LoyaltyCategoria",
]
