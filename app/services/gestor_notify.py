"""Push proativo do Agente Gestor (D-52, Fase C).

Monta o texto (pt-BR) do resumo diário e dos alertas e envia via WhatsApp para os
gestores (owner/manager com telefone cadastrado). Reusa `send_text` (com a trava
que protege staging) e a camada de cálculo `management`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import management
from app.services.whatsapp import send_text


def _brl(value: float) -> str:
    return f"R${value:,.0f}".replace(",", ".")


def build_digest_text(digest: dict) -> str:
    """Resumo diário em texto curto para WhatsApp."""
    lines = [f"📊 *Resumo do dia* — {digest['date']}", ""]
    lines.append(f"💰 Faturamento: {_brl(digest['revenue'])} ({digest['appointment_count']} atend.)")
    top = digest.get("top_barber")
    if top:
        lines.append(f"🏆 Destaque: {top['name']} ({_brl(top['revenue'])})")
    if digest.get("noshows"):
        lines.append(f"🚫 Faltas: {digest['noshows']}")
    if digest.get("ai_appointments"):
        lines.append(
            f"🤖 Pela IA: {digest['ai_appointments']} atend. ({_brl(digest['ai_revenue'])})"
        )
    idle = digest.get("tomorrow_idle_min") or 0
    if idle:
        h, m = divmod(int(idle), 60)
        idle_str = f"{h}h{m:02d}" if h else f"{m}min"
        lines.append(f"🗓️ Ociosidade amanhã: {idle_str} — vale puxar encaixes.")
    return "\n".join(lines)


def build_alert_text(alerts: list[dict]) -> str:
    """Concatena as mensagens de alerta numa única notificação."""
    header = "🔔 *Alerta de gestão*\n"
    return header + "\n".join(a["message"] for a in alerts)


async def _broadcast(db: AsyncSession, text: str) -> dict:
    phones = await management.manager_phones(db)
    sent = 0
    for phone in phones:
        if await send_text(phone=phone, message=text):
            sent += 1
    return {"recipients": len(phones), "sent": sent}


async def send_daily_digest(db: AsyncSession, target_date: date) -> dict:
    """Calcula e envia o resumo diário aos gestores."""
    digest = await management.daily_digest(db, target_date)
    result = await _broadcast(db, build_digest_text(digest))
    return {**result, "digest": digest}


async def send_alerts(db: AsyncSession, target_date: date) -> dict:
    """Calcula os alertas e, se houver, envia aos gestores."""
    alerts = await management.revenue_alerts(db, target_date)
    if not alerts:
        return {"alerts": 0, "recipients": 0, "sent": 0}
    result = await _broadcast(db, build_alert_text(alerts))
    return {"alerts": len(alerts), **result}
