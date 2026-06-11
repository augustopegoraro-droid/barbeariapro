"""Única fonte da verdade para RBAC: roles, prioridades e guards de acesso."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException, status as http_status

if TYPE_CHECKING:
    from models import Appointment

# ─── constantes ──────────────────────────────────────────────────────────────

ROLE_PRIORITY: dict[str, int] = {
    "owner": 4,
    "manager": 3,
    "reception": 2,
    "barber": 1,
}

# Roles com acesso ao painel admin (agenda, clientes, ações operacionais)
FULL_ACCESS: frozenset[str] = frozenset({"owner", "manager", "reception"})

# Roles com acesso a dados financeiros/equipe/relatórios (recepção excluída)
MANAGER_ACCESS: frozenset[str] = frozenset({"owner", "manager"})


# ─── resolução de role ────────────────────────────────────────────────────────

def resolve_role(unit_links: list) -> str:
    """Retorna a role de maior prioridade dentre os vínculos do usuário."""
    if not unit_links:
        return "barber"
    return max(
        (u.role.value for u in unit_links),
        key=lambda r: ROLE_PRIORITY.get(r, 0),
    )


def resolve_role_with_barber(unit_links: list) -> tuple[str, Optional[int]]:
    """Retorna (role, barber_id).

    barber_id é preenchido apenas quando a role efetiva é 'barber',
    permitindo filtros de propriedade em agendamentos.
    """
    if not unit_links:
        return "barber", None
    best = max(unit_links, key=lambda u: ROLE_PRIORITY.get(u.role.value, 0))
    barber_id = best.barber_id if best.role.value == "barber" else None
    return best.role.value, barber_id


# ─── guards ───────────────────────────────────────────────────────────────────

def require_full_access(role: str) -> None:
    """Lança HTTP 403 se a role não pertence ao conjunto admin (owner/manager/reception)."""
    if role not in FULL_ACCESS:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores.",
        )


def require_manager_access(role: str) -> None:
    """Lança HTTP 403 se a role não é owner ou manager. Recepção não tem acesso."""
    if role not in MANAGER_ACCESS:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a owner e manager.",
        )


def check_appointment_ownership(
    appt: "Appointment",
    role: str,
    my_barber_id: Optional[int],
) -> None:
    """Lança HTTP 403 se um barbeiro tenta agir sobre atendimento de outro."""
    if role in FULL_ACCESS:
        return
    if not any(item.barber_id == my_barber_id for item in appt.items):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Você não é o barbeiro deste atendimento.",
        )
