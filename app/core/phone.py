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
