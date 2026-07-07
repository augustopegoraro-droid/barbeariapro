# file: app/core/permissions.py
"""Catálogo canônico de permissões + matriz papel→permissões (fonte única).

Este módulo é a **fonte da verdade** do RBAC baseado em permissões (D1/D2 do
`ARQUITETURA_ALVO.md`). Ele alimenta:

- O **guard central** (`app/core/authz.py`): a resolução das permissões de um
  papel de SISTEMA vem daqui (código), sem depender de seed no banco — fail-safe.
- O **seed do banco** (`app/services/authz.py::sync_system_catalog`): faz upsert
  das tabelas `permissions`/`roles`/`role_permissions` a partir destas estruturas,
  para a UI de Papéis & Permissões e para os papéis personalizados.
- O `/me/permissions` (só UX no frontend).

Nomenclatura canônica: `recurso.subrecurso.ação`. Campos marcados
`sensitive_field=True` são redigidos no DTO quando falta a permissão (§1.4.5).

Alterou o catálogo? Rode `scripts/sync_authz_catalog.py` (ou o seed) para
refletir no banco; o teste `tests/test_authz_catalog.py` guarda contra drift.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    code: str
    description: str
    category: str
    sensitive_field: bool = False


# ─── Catálogo (fonte única) ─────────────────────────────────────────────────────
# Ordem = ordem de exibição na UI, agrupada por categoria.
CATALOG: tuple[Permission, ...] = (
    # Agenda
    Permission("schedule.own.view", "Ver a própria agenda", "Agenda"),
    Permission("schedule.own.manage", "Gerenciar a própria agenda", "Agenda"),
    Permission("schedule.all.view", "Ver a agenda de todos", "Agenda"),
    Permission("schedule.all.manage", "Gerenciar a agenda de todos", "Agenda"),
    Permission("schedule.reschedule.request", "Solicitar remarcação de turno", "Agenda"),
    Permission("schedule.reschedule.approve", "Aprovar remarcações", "Agenda"),
    # Clientes
    Permission("clients.view", "Ver clientes", "Clientes"),
    Permission("clients.manage", "Criar/editar clientes", "Clientes"),
    Permission("clients.delete", "Excluir/bloquear clientes", "Clientes"),
    Permission("clients.personal_data.view", "Ver dados pessoais (telefone/email/nascimento)", "Clientes", sensitive_field=True),
    Permission("clients.export", "Exportar clientes", "Clientes", sensitive_field=True),
    Permission("clients.bot_pause", "Pausar/reativar o bot de um cliente", "Clientes"),
    # CRM / Conversas
    Permission("crm.leads.view", "Ver leads/funil", "CRM"),
    Permission("crm.leads.manage", "Gerenciar leads/funil", "CRM"),
    Permission("conversations.view", "Ver conversas de WhatsApp", "CRM"),
    Permission("conversations.send", "Enviar mensagens", "CRM"),
    Permission("conversations.stream", "Receber a Inbox em tempo real (SSE)", "CRM"),
    # Financeiro
    Permission("finance.revenue.view", "Ver receita/faturamento", "Financeiro"),
    Permission("finance.margin.view", "Ver margem/lucro", "Financeiro", sensitive_field=True),
    Permission("finance.cost.view", "Ver custos", "Financeiro", sensitive_field=True),
    Permission("finance.payroll.view", "Ver folha/custo por profissional", "Financeiro", sensitive_field=True),
    Permission("finance.dre.view", "Ver DRE (resultado)", "Financeiro"),
    Permission("finance.cash.view", "Ver caixa/fechamentos", "Financeiro"),
    Permission("finance.payments.view", "Ver pagamentos/estornos", "Financeiro"),
    Permission("finance.expenses.manage", "Lançar/excluir despesas", "Financeiro"),
    Permission("finance.export", "Exportar dados financeiros", "Financeiro"),
    # Relatórios
    Permission("reports.dashboard.view", "Ver dashboard operacional (sem dinheiro)", "Relatórios"),
    Permission("reports.dashboard.financial.view", "Ver receita/ticket/comissão no dashboard", "Relatórios", sensitive_field=True),
    Permission("reports.operational.view", "Ver relatório operacional", "Relatórios"),
    Permission("reports.gestor.view", "Ver painel do Gestor", "Relatórios"),
    # Equipe / Serviços
    Permission("team.view", "Ver equipe", "Equipe"),
    Permission("team.manage", "Gerenciar equipe", "Equipe"),
    Permission("team.cost.view", "Ver custo/modelo de trabalho da equipe", "Equipe", sensitive_field=True),
    Permission("services.view", "Ver serviços", "Serviços"),
    Permission("services.manage", "Gerenciar serviços", "Serviços"),
    Permission("services.cost.view", "Ver custo dos serviços", "Serviços", sensitive_field=True),
    # Fidelidade / Pacotes
    Permission("loyalty.view", "Ver fidelidade", "Fidelidade"),
    Permission("loyalty.manage", "Configurar fidelidade", "Fidelidade"),
    Permission("memberships.view", "Ver assinaturas/pacotes", "Assinaturas"),
    Permission("memberships.sell", "Vender assinaturas/pacotes", "Assinaturas"),
    Permission("memberships.manage", "Gerenciar planos de assinatura", "Assinaturas"),
    # Billing (assinatura da própria org no SaaS)
    Permission("billing.view", "Ver a assinatura da empresa", "Empresa"),
    Permission("billing.manage", "Gerenciar a assinatura/pagamento da empresa", "Empresa"),
    # Integrações
    Permission("integrations.view", "Ver status das integrações", "Integrações"),
    Permission("integrations.whatsapp.manage", "Conectar/gerar QR do WhatsApp", "Integrações"),
    Permission("integrations.calendar.manage", "Conectar o Google Calendar", "Integrações"),
    # Configurações
    Permission("settings.company.manage", "Gerenciar cadastro/horários da empresa", "Configurações"),
    Permission("data.import", "Importar dados (clientes/financeiro) de outra ferramenta", "Configurações"),
    # Segurança / Governança (nova área)
    Permission("security.roles.manage", "Gerenciar papéis e permissões", "Segurança"),
    Permission("security.users.manage", "Gerenciar usuários e convites", "Segurança"),
    Permission("security.sessions.view", "Ver dispositivos e sessões", "Segurança"),
    Permission("security.sessions.revoke", "Revogar sessões", "Segurança"),
    Permission("security.audit.view", "Ver a auditoria", "Segurança"),
    Permission("security.audit.export", "Exportar a auditoria", "Segurança"),
    Permission("security.site_visibility.manage", "Configurar a visibilidade do site público", "Segurança"),
    Permission("analytics.view", "Ver analytics/insights", "Segurança"),
    Permission("privacy.lgpd.manage", "Gerenciar consentimento e dados do titular (LGPD)", "Segurança"),
    # IA
    Permission("ai.assistant.use", "Usar o assistente (Kernel IA) para navegar", "IA"),
    Permission("ai.finance.query", "Consultar finanças no chat da IA", "IA"),
)

ALL_CODES: frozenset[str] = frozenset(p.code for p in CATALOG)
SENSITIVE_FIELD_CODES: frozenset[str] = frozenset(
    p.code for p in CATALOG if p.sensitive_field
)


# ─── Papéis de sistema ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SystemRole:
    slug: str
    name: str
    color: str
    icon: str
    # is_assignable=False → papel derivado do modelo legado (owner/manager/reception/
    # barber) atribuído via `user_units`; ainda aparece na UI mas não é atribuído por
    # `user_roles`. Os papéis novos são atribuíveis via `user_roles`.
    is_assignable: bool = True


SYSTEM_ROLES: tuple[SystemRole, ...] = (
    SystemRole("owner", "Proprietário", "#f59e0b", "crown", is_assignable=False),
    SystemRole("partner", "Sócio", "#f97316", "handshake"),
    SystemRole("manager", "Gestor", "#3b82f6", "shield", is_assignable=False),
    SystemRole("reception", "Recepcionista", "#22c55e", "headset", is_assignable=False),
    SystemRole("barber", "Barbeiro", "#a855f7", "scissors", is_assignable=False),
    SystemRole("intern", "Estagiário", "#94a3b8", "graduation-cap"),
    SystemRole("finance", "Financeiro", "#14b8a6", "calculator"),
    SystemRole("marketing", "Marketing", "#ec4899", "megaphone"),
    SystemRole("support", "Atendimento", "#06b6d4", "message-circle"),
)


# ─── Blocos de permissão (compõem a matriz sem repetição) ───────────────────────
# Base operacional da recepção (Raquel). NÃO inclui `team.view` (a tela de Equipe
# com custos é manager-only) nem `schedule.reschedule.approve` (aprovar remarcação
# é ação de gestor) — ambos preservam a exclusão que o `require_manager_access` já
# fazia. A recepção lista profissionais/serviços pela própria Agenda
# (`schedule.all.view`/`services.view`), não pela tela de Equipe.
_OPERATIONS: frozenset[str] = frozenset({
    "schedule.all.view", "schedule.all.manage",
    "clients.view", "clients.manage", "clients.delete", "clients.personal_data.view",
    "clients.bot_pause",
    "crm.leads.view", "crm.leads.manage",
    "conversations.view", "conversations.send", "conversations.stream",
    "loyalty.view", "memberships.view", "memberships.sell",
    "services.view",
    "reports.dashboard.view", "reports.operational.view",
    "integrations.view", "ai.assistant.use",
})

_FINANCE: frozenset[str] = frozenset({
    "finance.revenue.view", "finance.margin.view", "finance.cost.view",
    "finance.payroll.view", "finance.dre.view", "finance.cash.view",
    "finance.payments.view", "finance.expenses.manage", "finance.export",
    "reports.dashboard.financial.view", "reports.gestor.view",
    "team.cost.view", "services.cost.view", "billing.view", "ai.finance.query",
})

# Conjunto completo (para o Proprietário) = todo o catálogo.
_ALL: frozenset[str] = ALL_CODES

# owner (Proprietário): tudo.
# partner (Sócio): tudo, menos billing e gestão de papéis.
# manager (Gestor): quase tudo, menos billing/papéis/LGPD (fiel ao comportamento
#   atual, em que owner e manager têm poderes quase idênticos).
_MANAGER: frozenset[str] = _ALL - frozenset({
    "billing.manage", "security.roles.manage", "privacy.lgpd.manage",
})

# reception (Recepcionista): operação, SEM financeiro. As ausências de
# `reports.dashboard.financial.view` e `integrations.whatsapp.manage` são as
# correções V5 e V6 (antes a recepção via faturamento no dashboard e podia gerar QR).
_RECEPTION: frozenset[str] = _OPERATIONS | frozenset({
    "clients.export",  # exportar contatos p/ campanhas — mantido do comportamento atual
})

# barber (Barbeiro): só a própria agenda + solicitar remarcação. A ausência de
# `conversations.stream` é a correção V4 (antes qualquer JWT da org, incl. barbeiro,
# recebia a Inbox inteira pelo SSE).
_BARBER: frozenset[str] = frozenset({
    "schedule.own.view", "schedule.own.manage", "schedule.reschedule.request",
    "ai.assistant.use",
})

_INTERN: frozenset[str] = frozenset({
    "schedule.own.view", "schedule.reschedule.request", "ai.assistant.use",
})

_FINANCE_ROLE: frozenset[str] = _FINANCE | frozenset({
    "reports.dashboard.view", "reports.operational.view",
    "clients.view", "ai.assistant.use", "team.view", "data.import",
})

_MARKETING: frozenset[str] = frozenset({
    "crm.leads.view", "crm.leads.manage",
    "conversations.view", "conversations.send", "conversations.stream",
    "clients.view", "clients.manage", "clients.personal_data.view", "clients.export",
    "loyalty.view", "loyalty.manage", "memberships.view",
    "analytics.view", "security.site_visibility.manage",
    "reports.dashboard.view", "reports.operational.view", "ai.assistant.use",
})

_SUPPORT: frozenset[str] = frozenset({
    "conversations.view", "conversations.send", "conversations.stream",
    "crm.leads.view", "crm.leads.manage",
    "clients.view", "clients.manage", "clients.personal_data.view", "clients.bot_pause",
    "loyalty.view", "memberships.view",
    "reports.dashboard.view", "ai.assistant.use",
})


# ─── Matriz papel→permissões (defaults dos papéis de sistema) ───────────────────
ROLE_DEFAULTS: dict[str, frozenset[str]] = {
    "owner": _ALL,
    "partner": _ALL - frozenset({"billing.manage", "security.roles.manage"}),
    "manager": _MANAGER,
    "reception": _RECEPTION,
    "barber": _BARBER,
    "intern": _INTERN,
    "finance": _FINANCE_ROLE,
    "marketing": _MARKETING,
    "support": _SUPPORT,
}


def permissions_for_system_role(slug: str) -> frozenset[str]:
    """Permissões default de um papel de sistema (vazio se slug desconhecido)."""
    return ROLE_DEFAULTS.get(slug, frozenset())
