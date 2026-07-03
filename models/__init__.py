"""Pacote de models.

Importa todos os módulos para que TODAS as classes sejam registradas no mesmo
`registry` (via `Base`) antes de qualquer configuração de mapper. É isso que
permite os `relationship()` resolverem classes-alvo entre módulos por nome.
"""

from __future__ import annotations

from .base import Base
from .enums import (
    AppointmentStatus,
    AttachmentMediaType,
    ConsentStatus,
    ContactChannel,
    ConversationStatus,
    DeliveryStatus,
    IntegrationProvider,
    IntegrationStatus,
    LoyaltyCategoria,
    LoyaltyLedgerType,
    LoyaltyNivel,
    LoyaltyStatus,
    LoyaltyVoucherStatus,
    MembershipStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    PaymentMethod,
    ServiceCategory,
    SubscriptionStatus,
    SyncStatus,
    UnitRole,
)
from .organization import Organization, Plan, Subscription
from .platform_admin import (
    PlatformAdmin,
    PlatformAuditLog,
    PlatformOnboardingOverride,
    PlatformOrgNote,
)
from .unit import BusinessHours, Unit
from .user import User, UserUnit
from .barber import Barber, BarberService, BarberUnit, TimeOff
from .client import Client, ClientConsent
from .service import Service
from .appointment import Appointment, AppointmentItem
from .payment import Expense, ExpenseCategory, Payment
from .debt import ClientDebt
from .cash_closing import CashDailyClosing
from .billing import (
    BillingCredit,
    BillingCustomer,
    BillingEvent,
    BillingPayment,
    Coupon,
    Discount,
    FeatureFlag,
    Invoice,
    PaymentAttempt,
    PlanFeature,
    PlanLimit,
    PlanPrice,
    UsageMetric,
    WebhookEvent,
)
from .appointment_reschedule import AppointmentRescheduleRequest
from .integration import CalendarSync, IntegrationAccount, MessageLog
from .loyalty import (
    ClientLoyalty,
    LoyaltyPointEntry,
    LoyaltyRule,
    LoyaltyTier,
    LoyaltyVoucher,
)
from .lead import Lead, LeadEvent
from .conversation import Attachment, Conversation, Message
from .membership import (
    ClientMembership,
    MembershipPlan,
    MembershipPlanItem,
    MembershipUsage,
)

__all__ = [
    "Base",
    # enums
    "AppointmentStatus",
    "AttachmentMediaType",
    "ConsentStatus",
    "ContactChannel",
    "ConversationStatus",
    "DeliveryStatus",
    "IntegrationProvider",
    "IntegrationStatus",
    "MembershipStatus",
    "MessageDirection",
    "MessageSenderType",
    "MessageType",
    "PaymentMethod",
    "ServiceCategory",
    "SubscriptionStatus",
    "SyncStatus",
    "UnitRole",
    # tenant
    "Organization",
    "Plan",
    "Subscription",
    "PlatformAdmin",
    "PlatformOrgNote",
    "PlatformOnboardingOverride",
    "PlatformAuditLog",
    # billing SaaS
    "PlanPrice",
    "FeatureFlag",
    "PlanFeature",
    "PlanLimit",
    "BillingCustomer",
    "Invoice",
    "BillingPayment",
    "PaymentAttempt",
    "Coupon",
    "Discount",
    "BillingCredit",
    "UsageMetric",
    "BillingEvent",
    "WebhookEvent",
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
    "ClientDebt",
    "CashDailyClosing",
    "AppointmentRescheduleRequest",
    # integrações
    "IntegrationAccount",
    "CalendarSync",
    "MessageLog",
    # fidelidade
    "ClientLoyalty",
    "LoyaltyTier",
    "LoyaltyRule",
    "LoyaltyVoucher",
    "LoyaltyPointEntry",
    "LoyaltyNivel",
    "LoyaltyStatus",
    "LoyaltyCategoria",
    "LoyaltyLedgerType",
    "LoyaltyVoucherStatus",
    # CRM / funil
    "Lead",
    "LeadEvent",
    # CRM conversacional
    "Conversation",
    "Message",
    "Attachment",
    # mensalidade / assinatura do cliente final
    "MembershipPlan",
    "MembershipPlanItem",
    "ClientMembership",
    "MembershipUsage",
]
