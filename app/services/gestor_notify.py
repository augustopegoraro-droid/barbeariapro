"""Push proativo do Agente Gestor (D-52, Fase C; D-97 acrescenta Web Push).

Monta o texto (pt-BR) do resumo diário e dos alertas e envia via WhatsApp para os
gestores (owner/manager com telefone cadastrado). Reusa `send_text` (com a trava
que protege staging) e a camada de cálculo `management`.

Os alertas de meta/queda (`revenue_alerts`) também disparam Web Push (D-96) para
os gestores com subscrição ativa — canal independente do WhatsApp (uma falha aqui
nunca impede o envio por WhatsApp, e vice-versa). A `idempotency_key` do push
inclui a DATA (não a hora) e o `user_id`: no máximo 1 push por tipo de alerta,
por gestor, por dia — mesmo com o cron rodando várias vezes ao dia. Isso é
deliberado (evitar fadiga de notificação): o resumo diário (`send_daily_digest`)
segue só por WhatsApp.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import management
from app.services import push as push_svc
from app.services.whatsapp import send_text
from models import PushSubscriberType

_logger = logging.getLogger(__name__)

_ALERT_TITLES = {
    "meta": "Meta do mês em risco 📉",
    "queda": "Queda no movimento ⚠️",
}


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


async def _broadcast_push(
    db: AsyncSession, *, org_id: int, target_date: date, alerts: list[dict]
) -> dict:
    """Dispara Web Push (1×/tipo/gestor/dia) além do WhatsApp. Nunca deixa uma
    falha de push derrubar o envio de WhatsApp (canais independentes)."""
    try:
        user_ids = await management.manager_user_ids(db)
        push_sent = push_skipped = 0
        for alert in alerts:
            title = _ALERT_TITLES.get(alert["type"], "Alerta de gestão 🔔")
            for user_id in user_ids:
                result = await push_svc.dispatch(
                    db,
                    org_id=org_id,
                    kind="gestor_alert",
                    idempotency_key=(
                        f"alert_push_v1:{alert['type']}:{org_id}:"
                        f"{target_date.isoformat()}:{user_id}"
                    ),
                    subscriber_type=PushSubscriberType.user,
                    user_id=user_id,
                    client_id=None,
                    appointment_id=None,
                    title=title,
                    body=alert["message"],
                    url="/admin/gestor",
                )
                push_sent += result == "sent"
                push_skipped += result != "sent"
        return {
            "push_targets": len(user_ids),
            "push_sent": push_sent,
            "push_skipped": push_skipped,
        }
    except Exception:
        _logger.exception(
            "gestor_notify: erro não tratado no push de alertas [org=%s date=%s]",
            org_id, target_date,
        )
        return {"push_targets": 0, "push_sent": 0, "push_skipped": 0}


async def send_alerts(
    db: AsyncSession, target_date: date, *, org_id: int | None = None
) -> dict:
    """Calcula os alertas e, se houver, envia aos gestores (WhatsApp + Web Push)."""
    alerts = await management.revenue_alerts(db, target_date)
    if not alerts:
        return {
            "alerts": 0, "recipients": 0, "sent": 0,
            "push_targets": 0, "push_sent": 0, "push_skipped": 0,
        }
    result = await _broadcast(db, build_alert_text(alerts))
    push_result = (
        await _broadcast_push(db, org_id=org_id, target_date=target_date, alerts=alerts)
        if org_id is not None
        else {"push_targets": 0, "push_sent": 0, "push_skipped": 0}
    )
    return {"alerts": len(alerts), **result, **push_result}
