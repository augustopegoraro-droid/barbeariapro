"""Kernel IA — detecção de intenção + autorização por papel (RBAC).

Camada pura (sem DB) que o endpoint `/kernel-ia/query` usa para, a partir do
texto livre do usuário: (1) detectar a intenção e (2) decidir se o papel do
usuário pode executá-la, ANTES de despachar qualquer tarefa.

Segurança por **allowlist com default-deny**: o barbeiro só pode as intenções
listadas em ``BARBER_ALLOWED_INTENTS``; qualquer outra — inclusive uma intenção
não reconhecida (``desconhecido``) ou uma operação de caixa "disfarçada" em texto
livre — é negada. A precisão do classificador NÃO é a barreira de segurança: mesmo
que ele erre e devolva ``desconhecido``, o default-deny recusa. Papéis de acesso
pleno (``rbac.FULL_ACCESS`` = owner/manager/reception) mantêm acesso total.

A detecção aqui é propositalmente simples (regras por palavra-chave). O NLU "de
verdade" é responsabilidade do n8n/OpenAI (D-49); este módulo é o ponto de
autorização que é a fonte da verdade, independente de onde a intenção nasce.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from app.core.rbac import FULL_ACCESS


class KernelIntent(str, Enum):
    """Intenções que o Kernel IA reconhece.

    As operações de caixa (abertura, fechamento, consulta de valores, sangria)
    mapeiam todas para ``CAIXA`` — o que importa para o RBAC é o grupo, todas
    proibidas para o barbeiro.
    """

    CONSULTAR_AGENDA = "consultar_agenda"
    SOLICITAR_REMARCACAO_TURNO = "solicitar_remarcacao_turno"
    GERENCIAR_FOLGA = "gerenciar_folga"
    CAIXA = "caixa"
    FINANCEIRO = "financeiro"
    DESCONHECIDO = "desconhecido"


# ─── matriz de permissões ──────────────────────────────────────────────────────
# Barbeiro: allowlist estrita. Tudo fora daqui é negado (default-deny).
BARBER_ALLOWED_INTENTS: frozenset[KernelIntent] = frozenset(
    {
        KernelIntent.CONSULTAR_AGENDA,
        KernelIntent.SOLICITAR_REMARCACAO_TURNO,
        KernelIntent.GERENCIAR_FOLGA,
    }
)


def is_intent_allowed(role: str, intent: KernelIntent) -> bool:
    """True se ``role`` pode executar ``intent``.

    owner/manager/reception (``FULL_ACCESS``) → acesso total. Qualquer outro papel
    (barbeiro e, por segurança, papéis inesperados) fica restrito à allowlist do
    barbeiro — fail-closed. ``DESCONHECIDO`` nunca está na allowlist, então um
    barbeiro com pedido não reconhecido é sempre negado.
    """
    if role in FULL_ACCESS:
        return True
    return intent in BARBER_ALLOWED_INTENTS


# ─── classificador de intenção (heurístico, best-effort) ───────────────────────

def _normalize(text: str) -> str:
    """minúsculas + remoção de acentos, para casar palavras-chave em pt-BR."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Ordem importa: intenções PROIBIDAS (caixa/financeiro) são checadas primeiro,
# para que um pedido de caixa "disfarçado" junto de outras palavras ainda caia em
# CAIXA e seja negado, em vez de ser reclassificado como algo permitido.
_CAIXA_KW = ("caixa", "sangria", "troco", "gaveta")
_FINANCEIRO_KW = ("fatura", "receita", "lucro", "balanco")  # "fatura" cobre faturamento/faturei/faturamos
_AGENDA_KW = ("agenda", "agendamento", "agendamentos", "atendimentos de", "meus horarios")
_TURNO_KW = ("turno", "escala", "realoca", "realocar", "remanejar")
_FOLGA_KW = ("folga", "folgas", "ausencia", "day off")


def _has(text: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text for kw in keywords)


def detect_intent(text: str) -> KernelIntent:
    """Classifica o texto livre numa ``KernelIntent`` (best-effort)."""
    t = _normalize(text)
    if _has(t, _CAIXA_KW):
        return KernelIntent.CAIXA
    if _has(t, _FINANCEIRO_KW):
        return KernelIntent.FINANCEIRO
    if _has(t, _AGENDA_KW):
        return KernelIntent.CONSULTAR_AGENDA
    if _has(t, _TURNO_KW):
        return KernelIntent.SOLICITAR_REMARCACAO_TURNO
    if _has(t, _FOLGA_KW):
        return KernelIntent.GERENCIAR_FOLGA
    return KernelIntent.DESCONHECIDO


# ─── decisão (intenção + autorização + mensagem) ───────────────────────────────

MSG_FORBIDDEN = "Essa ação não está disponível para o seu perfil."
MSG_UNKNOWN = (
    "Não entendi seu pedido. Posso ajudar com a sua agenda, seus turnos ou suas folgas."
)

# Mensagens de reconhecimento (o despacho real p/ os serviços é um follow-up;
# ver nota no endpoint). A de remarcação de turno é redigida como *solicitação*
# — cujo fluxo de aprovação ainda depende de definição de negócio.
_ACK: dict[KernelIntent, str] = {
    KernelIntent.CONSULTAR_AGENDA: "Certo! Vou buscar a sua agenda.",
    KernelIntent.SOLICITAR_REMARCACAO_TURNO: "Entendi. Vou encaminhar a sua solicitação de remarcação de turno.",
    KernelIntent.GERENCIAR_FOLGA: "Certo! Vou cuidar da sua folga.",
    KernelIntent.CAIXA: "Certo! Vou abrir o caixa.",
    KernelIntent.FINANCEIRO: "Certo! Vou levantar os números.",
}


@dataclass(frozen=True)
class KernelDecision:
    intent: KernelIntent
    allowed: bool
    message: str


def evaluate_request(role: str, text: str) -> KernelDecision:
    """Detecta a intenção do texto e decide se ``role`` pode executá-la.

    Retorna ``allowed=False`` (sem despacho) quando o pedido não é reconhecido ou
    quando o papel não tem permissão — com a mensagem clara correspondente, em vez
    de erro genérico ou (pior) execução indevida.
    """
    intent = detect_intent(text)
    if intent is KernelIntent.DESCONHECIDO:
        return KernelDecision(intent, False, MSG_UNKNOWN)
    if not is_intent_allowed(role, intent):
        return KernelDecision(intent, False, MSG_FORBIDDEN)
    return KernelDecision(intent, True, _ACK[intent])
