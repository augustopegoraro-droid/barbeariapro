"""
Patch do workflow n8n — aplica todas as correções de hardening.
Execução: python scripts/patch_workflow.py
"""
import json, copy, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "workflows.json"
DST = ROOT / "workflows.json"

with open(SRC) as f:
    data = json.load(f)

bot_wf = None
for wf in data:
    if wf.get("name") == "BarbeariaPro Bot - WhatsApp Chatbot":
        bot_wf = wf
        break

assert bot_wf, "Workflow BarbeariaPro Bot não encontrado"

nodes_by_id = {n["id"]: n for n in bot_wf["nodes"]}
nodes_by_name = {n["name"]: n for n in bot_wf["nodes"]}
conns = bot_wf["connections"]

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 1 — MÉDIO-1: maxIterations 15→8, temperature 0.75→0.3
# ─────────────────────────────────────────────────────────────
agent = nodes_by_id["agent-001"]
agent["parameters"]["options"]["maxIterations"] = 8
print("✓ maxIterations: 15 → 8")

llm = nodes_by_id["llm-001"]
llm["parameters"]["options"]["temperature"] = 0.3
print("✓ temperature: 0.75 → 0.3")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 2 — ALTO-4: Mover Send Composing para após filtro
# Set Phone → If Individual Message → Send Composing → [debounce]
# ─────────────────────────────────────────────────────────────

# Remover: Set Phone → Send Composing
conns["Set Phone"]["main"] = [[]]  # limpa
# Remover: Send Composing → If Individual Message
del conns["Send Composing"]

# Set Phone → If Individual Message
conns["Set Phone"]["main"] = [[{"node": "If Individual Message", "type": "main", "index": 0}]]

# If Individual Message[true] → Send Composing (em vez de direto para Code Debounce)
# If Individual Message[false] → [] (sem ação)
conns["If Individual Message"]["main"] = [
    [{"node": "Send Composing", "type": "main", "index": 0}],  # true
    [],                                                          # false
]

print("✓ Send Composing movido para após If Individual Message")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 3 — MÉDIO-3: Enhance Set Phone para extrair message + message_id
# ─────────────────────────────────────────────────────────────
set_phone = nodes_by_id["setphone-001"]
set_phone["parameters"]["assignments"]["assignments"] = [
    {"id": "sp1", "name": "phone",
     "value": "={{ $json.body.data.key.remoteJid.replace('@s.whatsapp.net', '').replace('@g.us', '') }}",
     "type": "string"},
    {"id": "sp2", "name": "fromMe",
     "value": "={{ $json.body.data.key.fromMe }}",
     "type": "boolean"},
    {"id": "sp3", "name": "remoteJid",
     "value": "={{ $json.body.data.key.remoteJid }}",
     "type": "string"},
    {"id": "sp4", "name": "message_id",
     "value": "={{ $json.body.data.key.id || '' }}",
     "type": "string"},
    # Extrai texto de todos os tipos de mensagem conhecidos
    {"id": "sp5", "name": "message",
     "value": (
         "={{ $json.body.data.message.conversation"
         " || $json.body.data.message.extendedTextMessage?.text"
         " || $json.body.data.message.imageMessage?.caption"
         " || ($json.body.data.message.audioMessage ? '[Cliente enviou áudio — por favor, escreva sua mensagem]' : '')"
         " || ($json.body.data.message.documentMessage ? '[Cliente enviou documento]' : '')"
         " || '' }}"
     ),
     "type": "string"},
]
print("✓ Set Phone agora extrai message + message_id + trata áudio/imagem")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 4 — CRÍTICO-1: Substituir Code Debounce por HTTP Request → FastAPI
# ─────────────────────────────────────────────────────────────
debounce_node = nodes_by_id["debounce-001"]
debounce_node["name"] = "HTTP Debounce"
debounce_node["type"] = "n8n-nodes-base.httpRequest"
debounce_node["typeVersion"] = 4.4
debounce_node["parameters"] = {
    "method": "POST",
    "url": "http://host.docker.internal:8000/bot/debounce",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "X-Bot-Token", "value": "barbearia-bot-key-2026-mvp-seguro"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={\n  \"phone\": \"+{{ $('Set Phone').item.json.phone }}\",\n  \"message\": \"{{ $('Set Phone').item.json.message }}\",\n  \"message_id\": \"{{ $('Set Phone').item.json.message_id }}\"\n}",
    "options": {},
}
# Atualizar conexão de entrada: Send Composing → HTTP Debounce
conns["Send Composing"] = {
    "main": [[{"node": "HTTP Debounce", "type": "main", "index": 0}]]
}
# Atualizar nome nas conexões de saída
conns["HTTP Debounce"] = conns.pop("Code Debounce", {
    "main": [[{"node": "IF Controller", "type": "main", "index": 0}]]
})
print("✓ Code Debounce substituído por HTTP Request → /bot/debounce")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 5 — IF Controller: agora verifica campo "proceed" (era "isController")
# ─────────────────────────────────────────────────────────────
if_ctrl = nodes_by_id["if-ctrl-001"]
if_ctrl["parameters"]["conditions"]["conditions"] = [{
    "id": "ctrl-c1",
    "leftValue": "={{ $json.proceed }}",
    "rightValue": True,
    "operator": {"type": "boolean", "operation": "true", "name": "filter.operator.true"},
}]
print("✓ IF Controller agora verifica $json.proceed (vem do FastAPI)")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 6 — CRÍTICO-1: Substituir Code Flush Buffer por HTTP Request → FastAPI
# ─────────────────────────────────────────────────────────────
flush_node = nodes_by_id["flush-001"]
flush_node["name"] = "HTTP Flush Buffer"
flush_node["type"] = "n8n-nodes-base.httpRequest"
flush_node["typeVersion"] = 4.4
flush_node["parameters"] = {
    "method": "POST",
    "url": "http://host.docker.internal:8000/bot/debounce/flush",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "X-Bot-Token", "value": "barbearia-bot-key-2026-mvp-seguro"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={\n  \"phone\": \"+{{ $('Set Phone').item.json.phone }}\"\n}",
    "options": {},
}
conns["HTTP Flush Buffer"] = conns.pop("Code Flush Buffer", {
    "main": [[{"node": "Code Horário Comercial", "type": "main", "index": 0}]]
})
print("✓ Code Flush Buffer substituído por HTTP Request → /bot/debounce/flush")

# Atualizar Wait 5s → HTTP Flush Buffer (era → Code Flush Buffer)
conns["Wait 5s"]["main"] = [[{"node": "HTTP Flush Buffer", "type": "main", "index": 0}]]

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 7 — ALTO-1: Code Horário Comercial lê phone de Set Phone,
# message de HTTP Flush Buffer, e adiciona prefixo [NOVA_SESSAO]
# ─────────────────────────────────────────────────────────────
hora_node = nodes_by_id["hora-001"]
hora_node["parameters"]["jsCode"] = """\
// Horário comercial real: seg-sex 9h-19h | sáb 9h-17h | dom fechado
// Palmas/TO = UTC-3 fixo (sem horário de verão)
const phone = $('Set Phone').item.json.phone;
const rawMessage = $json.message || '';
const isNewSession = $json.is_new_session === true;

// Prefixar [NOVA_SESSAO] para o agent resetar contexto interno
const message = isNewSession ? '[NOVA_SESSAO] ' + rawMessage : rawMessage;

const palmasMs = Date.now() + (-3 * 3600 * 1000);
const palmas = new Date(palmasMs);
const hour = palmas.getUTCHours();
const day = palmas.getUTCDay(); // 0=Dom, 1=Seg...6=Sáb
let isOpen = false;
if (day >= 1 && day <= 5) isOpen = hour >= 9 && hour < 19;
else if (day === 6)        isOpen = hour >= 9 && hour < 17;
return [{ json: { phone, message, isOpen, isNewSession } }];
"""
print("✓ Code Horário Comercial: phone via Set Phone, prefixo [NOVA_SESSAO]")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 8 — Send Response: usa phone de Set Phone (não mais de Flush Buffer)
# ─────────────────────────────────────────────────────────────
send_resp = nodes_by_id["sendresp-001"]
send_resp["parameters"]["jsonBody"] = (
    "={\n"
    "  \"number\": \"{{ $('Set Phone').item.json.phone }}\",\n"
    "  \"text\": \"{{ $json.output }}\"\n"
    "}"
)
print("✓ Send Response: phone referencia Set Phone diretamente")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 9 — Tool: Cancelar Agendamento — adicionar phone como query param
# ─────────────────────────────────────────────────────────────
t_cancel = nodes_by_id["t-cancel"]
t_cancel["parameters"]["url"] = (
    "={{ 'http://host.docker.internal:8000/bot/appointments/' "
    "+ $fromAI('appointment_id', 'ID numerico do agendamento', 'number') "
    "+ '/cancel' }}"
)
# Adicionar sendQuery com phone
t_cancel["parameters"]["sendQuery"] = True
t_cancel["parameters"]["queryParameters"] = {
    "parameters": [
        {
            "name": "phone",
            "value": "={{ $fromAI('phone', 'Telefone E.164 do cliente com + (ex +5563999368196)', 'string') }}"
        }
    ]
}
t_cancel["parameters"]["description"] = (
    "Cancela agendamento pelo ID numerico. "
    "OBRIGATORIO: appointment_id (number) E phone=telefone E.164 do cliente com + para verificacao de propriedade. "
    "NUNCA chame sem confirmar o horário com o cliente primeiro."
)
print("✓ Tool Cancelar Agendamento: adicionado phone query param (ownership check)")

# ─────────────────────────────────────────────────────────────
# CORREÇÃO 10 — System Prompt: autonomia reduzida, remarcar, confirmação
# ─────────────────────────────────────────────────────────────
new_system_prompt = """\
Você é Raquel, recepcionista da Barbearia Taylor & Thedy em Palmas-TO.

Você trabalha aqui há anos. Conhece o Taylor, o Thedy, cada cliente, a rotina da barbearia de ponta a ponta.

Você conversa pelo WhatsApp como uma funcionária de verdade. NUNCA mencione IA, chatbot, assistente virtual ou sistema. NUNCA use linguagem robótica.

━━━ INÍCIO DE TODA CONVERSA ━━━
Antes de responder qualquer mensagem, chame obter_perfil_cliente(phone=+NUMERO).

Se a mensagem começar com [NOVA_SESSAO], trate como início de conversa completamente nova — esqueça qualquer contexto de atendimento anterior (horários verificados, serviços discutidos, etc.) e comece do zero com uma saudação adequada.

Com o perfil em mãos, você sabe como abordar:

Cliente novo (found=false) → seja acolhedora:
"Oi! Bem-vindo à Taylor & Thedy 😊 Como posso te ajudar?"

Cliente recorrente (days_since_last_visit ≤ 45) → reconheça pelo nome:
"Bom te ver de novo, {nome}! Quer cortar com o {barbeiro_favorito} de novo?"
"Oi {nome}! Que saudade 😄 Quer agendar?"

Cliente inativo (days_since_last_visit > 45) → toque leve, sem cobrar:
"Ei {nome}! Sumido hein 😄 Faz um tempão. Vamos deixar esse visual em dia?"
Nunca pressione. Nunca cobre.

━━━ A BARBEARIA ━━━
Barbearia Taylor & Thedy — Palmas/TO
Referência em corte masculino na cidade. Fundada pelo Taylor e pelo Thedy.

━━━ OS BARBEIROS ━━━
Taylor (id=1): cortes clássicos e modernos. Detalhista, preciso. Acabamento impecável.
Thedy (id=2): barba, acabamento e coloração. Descontraído. Referência em pigmentação de barba na região.

Sugestão por serviço:
- Corte → Taylor
- Barba / coloração → Thedy
- Cliente com histórico → sugira o barbeiro favorito do perfil

━━━ COMO VOCÊ FALA ━━━
Mensagens curtas — máximo 2-3 linhas por resposta.
Use o nome do cliente sempre que souber.
Varie as respostas. Nunca repita a mesma frase.
Emojis moderados, como uma pessoa real usaria no WhatsApp.
Sem formalidade excessiva. Sem textão. Sem listas longas.

✅ BOM:
"Deixa eu ver aqui... ele tem às 9h, 10h30 ou 14h. Qual prefere?"
"Prontinho! Reservado com o Taylor na quinta às 9h 🙌 Te esperamos!"
"Feito! Cancelei seu horário. Quando quiser remarcar é só chamar 😊"
"Corte e barba? Fica ainda mais caprichado 😄"

❌ RUIM:
"Olá, como posso ajudá-lo hoje?"
"Verificando disponibilidade no sistema."
"Agendamento realizado com sucesso."
"Por favor, informe a data desejada."
"Posso ajudá-lo com mais alguma coisa?"

━━━ CONTEXTO LOCAL ━━━
Se o cliente mencionar calor de Palmas, chuva, Copa do Mundo 2026, Seleção, feriado ou evento local → comente brevemente com naturalidade, depois volte ao foco. NUNCA inicie esses assuntos. Um comentário curto, nada mais.

━━━ VENDA CONSULTIVA ━━━
Uma vez por conversa, quando fizer sentido, sugira barba junto com o corte:
"Se quiser aproveitar, dá pra encaixar barba com o Thedy também 😉"
"Esse horário dá tranquilo pra corte e barba."
Nunca insista. Uma sugestão só. Sem pressão.

━━━ FLUXO PARA AGENDAR ━━━
1. obter_perfil_cliente(phone=+NUMERO) — identifique quem é
2. Descobrir serviço — use listar_servicos se precisar mostrar opções
3. Descobrir barbeiro — sugira pelo histórico do perfil ou pelo tipo de serviço
4. Descobrir a data — use a data atual do contexto para "amanhã", "semana que vem" etc.
5. verificar_disponibilidade(barber_id, service_id, date=YYYY-MM-DD)
6. Apresentar horários humanamente: "Ele tem às 9h, 10h30 ou 14h. Qual prefere?"
7. Confirmar o horário escolhido com o cliente
8. Perguntar o nome se ainda não souber
9. cadastrar_cliente(phone=NUMERO_SEM_MAIS, name=NOME)
   ⚠ NUMERO SEM o + (ex: 5563999368196)
10. criar_agendamento(client_id, barber_id, service_id, start_at=ISO-03:00)
    ⚠ Formato obrigatório: 2026-06-10T09:00:00-03:00
    ⚠ SOMENTE use horários que vieram de verificar_disponibilidade NESTA conversa
11. Confirmar com simpatia: "Prontinho! Você tá reservado com o {barbeiro} na {dia} às {hora}. Te esperamos! 😊"

Se criar_agendamento retornar erro 409 (conflito): chame verificar_disponibilidade novamente
para esse mesmo dia e barbeiro e ofereça os horários disponíveis atualizados. Não tente o mesmo horário.

Se verificar_disponibilidade retornar lista vazia por 2 tentativas (datas/barbeiros diferentes):
informe que não há horários no período e sugira ligar para a barbearia.

━━━ FLUXO PARA CONSULTAR ━━━
→ consultar_agendamentos(phone=+NUMERO_COM_MAIS)
→ Apresente naturalmente: "Você tem horário com o Taylor na quarta às 14h 😊"
→ Se vazio: "Você não tem nada marcado ainda. Quer agendar?"

━━━ FLUXO PARA CANCELAR ━━━
1. consultar_agendamentos(phone=+NUMERO) — listar os horários ativos
2. Mostrar o que encontrou de forma clara e humana
3. OBRIGATÓRIO: Confirmar com o cliente qual horário ele quer cancelar
   "Tem certeza que quer cancelar seu horário com o {barbeiro} na {dia} às {hora}?"
4. Só após confirmação explícita do cliente:
   cancelar_agendamento(appointment_id=ID, phone=+NUMERO_COM_MAIS)
   ⚠ SEMPRE passe o phone — é obrigatório para segurança
5. "Feito! Cancelei seu horário. Quando quiser remarcar é só chamar 😊"

━━━ FLUXO PARA REMARCAR ━━━
1. consultar_agendamentos → identificar agendamento atual
2. verificar_disponibilidade na nova data/barbeiro desejado
3. SE houver horário disponível: mostrar ao cliente e confirmar
4. Só após confirmação: cancelar_agendamento (agendamento atual)
5. criar_agendamento (novo horário)
⚠ NUNCA cancele o agendamento atual ANTES de confirmar disponibilidade no novo horário.
⚠ Se não houver horário na nova data, informe ANTES de cancelar qualquer coisa.

━━━ REGRAS ABSOLUTAS ━━━
NUNCA invente horários ou disponibilidade — sempre consulte os endpoints.
NUNCA mencione IA, chatbot, sistema ou automação.
NUNCA use frases que soam automatizadas ou robóticas.
NUNCA chame criar_agendamento sem ter chamado verificar_disponibilidade NESTA conversa para o mesmo barbeiro/dia.
NUNCA chame cancelar_agendamento sem antes confirmar explicitamente com o cliente qual horário será cancelado.
NUNCA chame cancelar_agendamento sem passar o phone= do cliente.
SEMPRE confirme os dados antes de criar um agendamento.
SEMPRE chame obter_perfil_cliente no início de cada nova conversa.

━━━ TRATAMENTO DE ERROS ━━━
Se qualquer ferramenta retornar erro: informe o cliente de forma natural e amigável.
"Ops, tive um probleminha aqui. Pode tentar de novo em instantes? 😊"
Não tente adivinhar resultados de chamadas que falharam. Não prossiga sem dados confirmados.
"""

agent["parameters"]["options"]["systemMessage"] = new_system_prompt
print("✓ System prompt atualizado: nova sessão, remarcar, confirmação cancelamento, regras de autonomia")

# ─────────────────────────────────────────────────────────────
# Verificar consistência das conexões (nomes devem existir)
# ─────────────────────────────────────────────────────────────
all_node_names = {n["name"] for n in bot_wf["nodes"]}
errors = []
for src, targets in conns.items():
    if src not in all_node_names:
        errors.append(f"Connection source '{src}' não existe como nó")
    for port_list in targets.values():
        for dest_list in port_list:
            for dest in dest_list:
                if dest.get("node") and dest["node"] not in all_node_names:
                    errors.append(f"Connection dest '{dest['node']}' não existe como nó")

if errors:
    print("\n❌ ERROS DE CONSISTÊNCIA:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("\n✓ Consistência das conexões: OK")

# Serializar
with open(DST, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=None, separators=(",", ":"))

print(f"\n✅ Workflow salvo em {DST}")
print("   Próximo passo: importar no n8n e testar")
