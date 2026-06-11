"""Enums tipados espelhando 1:1 os tipos ENUM do PostgreSQL.

Cada classe herda de `str` para serialização natural (JSON/logs) e tem
`value == label do PG`. O helper `pg_enum` cria a coluna SQLAlchemy amarrada
ao tipo nativo já existente no banco (`create_type=False`, pois os tipos foram
criados pelo schema SQL e não devem ser recriados pelos models).
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Coluna ENUM nativa do PG, sem tentar (re)criar o tipo."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        create_type=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


class SubscriptionStatus(str, enum.Enum):
    trial = "trial"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"


class UnitRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    reception = "reception"
    barber = "barber"


class ServiceCategory(str, enum.Enum):
    cabelo = "cabelo"
    barba = "barba"
    combo = "combo"
    quimica = "quimica"
    estetica = "estetica"


class ContactChannel(str, enum.Enum):
    whatsapp = "whatsapp"
    instagram = "instagram"
    google = "google"
    indicacao = "indicacao"
    passante = "passante"


class AppointmentStatus(str, enum.Enum):
    agendado = "agendado"
    concluido = "concluido"
    cancelado = "cancelado"
    faltou = "faltou"


class PaymentMethod(str, enum.Enum):
    dinheiro = "dinheiro"
    cartao = "cartao"
    pix = "pix"


class ConsentStatus(str, enum.Enum):
    opt_in = "opt_in"
    opt_out = "opt_out"


class IntegrationProvider(str, enum.Enum):
    google_calendar = "google_calendar"
    whatsapp = "whatsapp"


class IntegrationStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"
    error = "error"


class SyncStatus(str, enum.Enum):
    pending = "pending"
    synced = "synced"
    failed = "failed"


class MessageDirection(str, enum.Enum):
    outbound = "outbound"
    inbound = "inbound"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"


class LoyaltyNivel(str, enum.Enum):
    novo = "novo"
    ativo = "ativo"
    fiel = "fiel"
    vip = "vip"


class LoyaltyStatus(str, enum.Enum):
    ativo = "ativo"
    em_risco = "em_risco"
    inativo = "inativo"


class LoyaltyCategoria(str, enum.Enum):
    bronze = "bronze"
    prata = "prata"
    ouro = "ouro"
    diamante = "diamante"
