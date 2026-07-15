"""Normalização canônica de telefone E.164 — única fonte para painel, bot e seed."""

from __future__ import annotations

import re

_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


def normalize_phone(raw: str) -> str:
    """Normaliza para E.164, assumindo Brasil (+55) quando o código do país falta.

    Aceita: '+5563992287396', '5563992287396', '63992287396', '(63) 99228-7396'.
    Números sem '+' e sem prefixo 55 ganham '+55'; com prefixo 55 e tamanho de
    número internacional completo (12+ dígitos) ganham apenas '+'.
    Levanta ValueError se o resultado não for E.164 válido.
    """
    p = raw.strip()
    digits = re.sub(r"\D", "", p)
    if p.startswith("+"):
        candidate = "+" + digits
    elif digits.startswith("55") and len(digits) >= 12:
        candidate = "+" + digits
    else:
        candidate = "+55" + digits
    if not _E164.match(candidate):
        raise ValueError(f"Telefone fora do formato E.164: {candidate!r}")
    return candidate


def mask_phone(phone: str | None) -> str:
    """Mascara para log (LGPD, V14): mantém DDI+DDD e os 2 últimos dígitos.

    `+5563992287396` → `+5563***396`. Nunca levanta — entra o que vier,
    inclusive já malformado; é só para log, não para persistência/validação.
    """
    if not phone:
        return "-"
    if len(phone) <= 6:
        return "*" * len(phone)
    return f"{phone[:6]}***{phone[-3:]}"
