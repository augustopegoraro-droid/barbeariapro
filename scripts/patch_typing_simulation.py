"""
Patch: simulação de digitação humana — Move Send Composing para após IF Horário Aberto,
adiciona Wait 1s + Send Composing Active (delay:30000) para cobrir todo o AI processing.

Execução: python scripts/patch_typing_simulation.py
"""
import json, sys
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

nodes = bot_wf["nodes"]
nodes_by_id = {n["id"]: n for n in nodes}
nodes_by_name = {n["name"]: n for n in nodes}
conns = bot_wf["connections"]

# ─────────────────────────────────────────────────────────────
# 1 — Reposicionar Send Composing (composing-001)
#     Era: entre If Individual Message e HTTP Debounce (t≈0.1s, delay expira antes do AI)
#     Será: após IF Horário Aberto [true] (t≈5.6s, cobre o inicio do AI)
# ─────────────────────────────────────────────────────────────
composing = nodes_by_id["composing-001"]
composing["position"] = [1440, -120]
# Mantém delay:2000 — animação inicial de "começando a digitar"
# $json.phone aqui vem de Code Horário Comercial (que retorna {phone, message, isOpen, isNewSession})
print("✓ Send Composing reposicionado para [1440, -120]")

# ─────────────────────────────────────────────────────────────
# 2 — Adicionar Wait Typing Init (1 segundo)
#     Cria pausa entre animação inicial e o composing de longa duração
# ─────────────────────────────────────────────────────────────
wait_typing = {
    "parameters": {
        "amount": 1,
        "unit": "seconds"
    },
    "type": "n8n-nodes-base.wait",
    "typeVersion": 1.1,
    "position": [1640, -120],
    "id": "wait-typing-001",
    "name": "Wait Typing Init",
    "webhookId": "typing-init-wait-barbearia"
}
nodes.append(wait_typing)
print("✓ Wait Typing Init adicionado (1s, posição [1640, -120])")

# ─────────────────────────────────────────────────────────────
# 3 — Adicionar Send Composing Active (delay:30000)
#     Mantém "digitando..." ativo por até 30s — cobre todo o AI processing.
#     Quando Send Response dispara, o indicador some automaticamente.
# ─────────────────────────────────────────────────────────────
composing_active = {
    "parameters": {
        "method": "POST",
        "url": "http://host.docker.internal:8080/chat/sendPresence/Barbearia",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {
                    "name": "apikey",
                    "value": "={{ $env.EVOLUTION_API_KEY }}"
                }
            ]
        },
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={\n"
            "  \"number\": \"{{ $('Set Phone').item.json.phone }}\",\n"
            "  \"presence\": \"composing\",\n"
            "  \"delay\": 30000\n"
            "}"
        ),
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.4,
    "position": [1840, -120],
    "id": "composing-active-001",
    "name": "Send Composing Active"
}
nodes.append(composing_active)
print("✓ Send Composing Active adicionado (delay:30000ms, posição [1840, -120])")

# ─────────────────────────────────────────────────────────────
# 4 — Atualizar AI Agent: referência explícita a Code Horário Comercial
#     MOTIVO: após a chain de composing, $json é o response da Evolution API,
#     não mais os dados do workflow. Usar $('Code Horário Comercial').item.json.* é seguro.
# ─────────────────────────────────────────────────────────────
agent = nodes_by_id["agent-001"]
agent["parameters"]["text"] = (
    "={{ '[WhatsApp: +' + $('Code Horário Comercial').item.json.phone + ']\\n"
    "[Data e hora: ' + $now.toISO() + ' (Palmas/TO, UTC-3)]\\n' "
    "+ $('Code Horário Comercial').item.json.message }}"
)
print("✓ AI Agent: text usa $('Code Horário Comercial').item.json.phone/message")

# ─────────────────────────────────────────────────────────────
# 5 — Atualizar conexões
# ─────────────────────────────────────────────────────────────

# 5a — If Individual Message [true] → HTTP Debounce (era → Send Composing)
conns["If Individual Message"]["main"][0] = [
    {"node": "HTTP Debounce", "type": "main", "index": 0}
]
print("✓ If Individual Message [true] → HTTP Debounce (direto, sem composing prematuro)")

# 5b — Send Composing → Wait Typing Init (era → HTTP Debounce)
conns["Send Composing"] = {
    "main": [[{"node": "Wait Typing Init", "type": "main", "index": 0}]]
}
print("✓ Send Composing → Wait Typing Init")

# 5c — Wait Typing Init → Send Composing Active
conns["Wait Typing Init"] = {
    "main": [[{"node": "Send Composing Active", "type": "main", "index": 0}]]
}
print("✓ Wait Typing Init → Send Composing Active")

# 5d — Send Composing Active → AI Agent
conns["Send Composing Active"] = {
    "main": [[{"node": "AI Agent", "type": "main", "index": 0}]]
}
print("✓ Send Composing Active → AI Agent")

# 5e — IF Horário Aberto [true] → Send Composing (era → AI Agent)
conns["IF Horário Aberto"]["main"][0] = [
    {"node": "Send Composing", "type": "main", "index": 0}
]
print("✓ IF Horário Aberto [true] → Send Composing (composing agora protegido por horário)")

# ─────────────────────────────────────────────────────────────
# 6 — Verificação de consistência
# ─────────────────────────────────────────────────────────────
# Rebuild name index after adding new nodes
nodes_by_name = {n["name"]: n for n in nodes}
all_node_names = set(nodes_by_name.keys())

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

# ─────────────────────────────────────────────────────────────
# Serializar
# ─────────────────────────────────────────────────────────────
with open(DST, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=None, separators=(",", ":"))

print(f"\n✅ Workflow salvo em {DST}")
print("\nPróximos passos:")
print("  1. docker cp workflows.json n8n:/tmp/ && docker exec n8n n8n import:workflow --input=/tmp/workflows.json")
print("  2. docker exec n8n n8n publish:workflow --id=25QZQ664N6hrIg59 && docker restart n8n")
print("  3. Enviar mensagem de teste e verificar composing durante o AI processing")
