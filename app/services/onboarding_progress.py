"""Progresso de onboarding das orgs — visão da PLATAFORMA (superadmin M6).

As 11 etapas espelham o funil de ativação do produto. Cada etapa é DERIVADA dos
dados reais da org (sinais da função `app_platform_onboarding_signals`, migration
0031) e pode ser SOBRESCRITA manualmente pelo superadmin (overrides na tabela
`platform_onboarding_overrides` — presença de override vence a derivação).

A regra de negócio fica em Python de propósito: versionada com o código,
testável, e os limiares mudam sem migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# (key, rótulo) na ordem do funil.
STAGES: tuple[tuple[str, str], ...] = (
    ("conta_criada", "Conta criada"),
    ("primeiro_acesso", "Primeiro acesso"),
    ("cadastro_empresa", "Cadastro da empresa"),
    ("profissionais", "Cadastro dos profissionais"),
    ("servicos", "Cadastro dos serviços"),
    ("importacao_clientes", "Importação dos clientes"),
    ("primeiro_agendamento", "Primeiro agendamento"),
    ("whatsapp", "WhatsApp configurado"),
    ("financeiro", "Financeiro configurado"),
    ("primeiro_recebimento", "Primeiro recebimento"),
    ("cliente_ativo", "Cliente ativo"),
)
STAGE_KEYS: frozenset[str] = frozenset(k for k, _ in STAGES)
STAGE_LABELS: dict[str, str] = dict(STAGES)

# Limiares da derivação (decisão documentada em docs/superadmin/decisions.md):
# - "importou clientes" = base mínima de 10 (1–2 podem ser testes manuais);
# - "cliente ativo" = uso real recente (≥5 agendamentos nos últimos 30 dias).
CLIENTS_IMPORT_THRESHOLD = 10
ACTIVE_APPT_30D_THRESHOLD = 5


def derive_auto(signals: dict) -> dict[str, Optional[bool]]:
    """Derivação automática por etapa. None = não derivável (só manual).

    `primeiro_acesso` não tem evento registrado no sistema (não há tabela de
    logins) — fica pendente até marcação manual ou até existir o evento.
    """
    return {
        "conta_criada": True,
        "primeiro_acesso": None,
        "cadastro_empresa": bool(signals["has_profile"]),
        "profissionais": signals["barbers_count"] >= 1,
        "servicos": signals["services_count"] >= 1,
        "importacao_clientes": signals["clients_count"] >= CLIENTS_IMPORT_THRESHOLD,
        "primeiro_agendamento": signals["appointments_count"] >= 1,
        "whatsapp": bool(signals["wa_configured"]),
        "financeiro": (
            signals["expenses_count"] >= 1
            or bool(signals["has_revenue_goal"])
            or signals["payments_count"] >= 1
        ),
        "primeiro_recebimento": signals["payments_count"] >= 1,
        "cliente_ativo": signals["appt_30d"] >= ACTIVE_APPT_30D_THRESHOLD,
    }


def compute_checklist(signals: dict, overrides: dict[str, bool]) -> list[dict]:
    """Checklist final da org: override manual > derivação > pendente."""
    auto = derive_auto(signals)
    items: list[dict] = []
    for key, label in STAGES:
        if key in overrides:
            done, source = overrides[key], "manual"
        else:
            derived = auto[key]
            done, source = (bool(derived), "auto")
        items.append(
            {
                "key": key,
                "label": label,
                "done": done,
                "source": source,
                "derivable": auto[key] is not None,
            }
        )
    return items


def current_stage(items: list[dict]) -> Optional[dict]:
    """Primeira etapa pendente na ordem do funil; None = onboarding completo."""
    return next((i for i in items if not i["done"]), None)


def stuck_days(signals: dict, *, now: Optional[datetime] = None) -> int:
    """Dias sem atividade (proxy de 'parada'): última atividade ou criação."""
    ref = signals.get("last_activity") or signals.get("created_at")
    if ref is None:
        return 0
    now = now or datetime.now(timezone.utc)
    return max(int((now - ref).total_seconds() // 86_400), 0)


def trial_days_left(signals: dict, *, now: Optional[datetime] = None) -> Optional[int]:
    """Dias restantes de trial; None quando a org não está em trial."""
    if signals.get("sub_status") != "trial" or signals.get("sub_period_end") is None:
        return None
    now = now or datetime.now(timezone.utc)
    return int((signals["sub_period_end"] - now).total_seconds() // 86_400)
