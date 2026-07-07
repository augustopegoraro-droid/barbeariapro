"""Testes unitários do catálogo de permissões e da matriz papel→permissões.

Puros (sem banco) — guardam contra drift e travam as correções de auditoria
(V4/V5/V6/V7) como invariantes do default de cada papel de sistema.
"""

from __future__ import annotations

from app.core.permissions import (
    ALL_CODES,
    CATALOG,
    ROLE_DEFAULTS,
    SENSITIVE_FIELD_CODES,
    SYSTEM_ROLES,
    permissions_for_system_role,
)


def test_catalog_codes_are_unique():
    codes = [p.code for p in CATALOG]
    assert len(codes) == len(set(codes))


def test_role_defaults_only_reference_known_codes():
    for slug, perms in ROLE_DEFAULTS.items():
        unknown = perms - ALL_CODES
        assert not unknown, f"{slug} referencia permissões fora do catálogo: {unknown}"


def test_every_system_role_has_a_default_set():
    for role in SYSTEM_ROLES:
        assert role.slug in ROLE_DEFAULTS, f"papel {role.slug} sem defaults"


def test_owner_has_the_whole_catalog():
    assert ROLE_DEFAULTS["owner"] == ALL_CODES


def test_manager_excludes_owner_only_permissions():
    m = ROLE_DEFAULTS["manager"]
    assert "billing.manage" not in m
    assert "security.roles.manage" not in m
    assert "privacy.lgpd.manage" not in m
    # mas mantém o poder financeiro/operacional
    assert "finance.revenue.view" in m
    assert "reports.dashboard.financial.view" in m


def test_reception_default_closes_v5_and_v6():
    r = ROLE_DEFAULTS["reception"]
    # V5: recepção não vê financeiro no dashboard
    assert "reports.dashboard.financial.view" not in r
    assert "finance.revenue.view" not in r
    # V6: recepção não conecta/gera QR do WhatsApp
    assert "integrations.whatsapp.manage" not in r
    # ...mas mantém o operacional do dia a dia
    assert "reports.dashboard.view" in r
    assert "integrations.view" in r
    assert "clients.bot_pause" in r
    assert "schedule.all.manage" in r


def test_barber_default_closes_v4_and_v7():
    b = ROLE_DEFAULTS["barber"]
    # V4: barbeiro não recebe a Inbox em tempo real
    assert "conversations.stream" not in b
    # V7: barbeiro não pausa o bot de clientes
    assert "clients.bot_pause" not in b
    # sem dado financeiro
    assert "finance.revenue.view" not in b
    # mantém a própria agenda
    assert "schedule.own.view" in b
    assert "schedule.own.manage" in b


def test_sensitive_fields_are_in_catalog():
    assert SENSITIVE_FIELD_CODES <= ALL_CODES
    assert "finance.margin.view" in SENSITIVE_FIELD_CODES
    assert "reports.dashboard.financial.view" in SENSITIVE_FIELD_CODES
    assert "clients.personal_data.view" in SENSITIVE_FIELD_CODES


def test_permissions_for_unknown_role_is_empty():
    assert permissions_for_system_role("inexistente") == frozenset()
