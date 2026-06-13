"""
Fix crítico: migra todos os 8 tools do formato antigo n8n (headerParameters/queryParameters/$fromAI())
para o formato v1.1 correto (parametersHeaders/parametersQuery/valueProvider: modelRequired).

Causa do erro "Received tool input did not match expected schema ✖ Required → at ":
- sendHeaders:true + parametersHeaders ausente → n8n usa default {values:[{name:""}]}
- makeToolInputSchema([{name:"",required:true}]) → z.object({"": z.string()})
- Todo tool call falha: campo "" obrigatório nunca é preenchido pelo LLM
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
with open(ROOT / "workflows.json") as f:
    data = json.load(f)

bot_wf = next(w for w in data if "BarbeariaPro Bot" in w.get("name", ""))
nodes = {n["id"]: n for n in bot_wf["nodes"]}

BOT_TOKEN = os.environ.get("BOT_API_KEY", "")

# ─── HEADER ESTÁTICO (igual em todos os tools) ───────────────────────────────
STATIC_HEADER = {
    "parametersHeaders": {
        "values": [
            {"name": "X-Bot-Token", "valueProvider": "fieldValue", "value": BOT_TOKEN}
        ]
    }
}

STATIC_HEADER_JSON = {
    "parametersHeaders": {
        "values": [
            {"name": "X-Bot-Token", "valueProvider": "fieldValue", "value": BOT_TOKEN},
            {"name": "Content-Type", "valueProvider": "fieldValue", "value": "application/json"},
        ]
    }
}

def fix_headers(p: dict, with_content_type=False) -> None:
    """Remove headerParameters, adiciona parametersHeaders correto."""
    p.pop("headerParameters", None)
    p.update(STATIC_HEADER_JSON if with_content_type else STATIC_HEADER)


def set_query(p: dict, params: list[dict]) -> None:
    """Define parametersQuery no formato correto, remove queryParameters."""
    p.pop("queryParameters", None)
    p["specifyQuery"] = "keypair"
    p["parametersQuery"] = {"values": params}


def set_placeholder_defs(p: dict, defs: list[dict]) -> None:
    p["placeholderDefinitions"] = {"values": defs}


def set_json_body(p: dict, body_template: str, defs: list[dict]) -> None:
    """Define body como JSON puro com {placeholder}, remove sendBody via $fromAI."""
    p.pop("jsonBody", None)
    p["specifyBody"] = "json"
    p["jsonBody"] = body_template
    set_placeholder_defs(p, defs)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Tool: Obter Perfil Cliente (t-profile)
#    GET /bot/clients/profile?phone=+5563...
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-profile"]["parameters"]
fix_headers(p)
set_query(p, [{"name": "phone", "valueProvider": "modelRequired"}])
set_placeholder_defs(p, [
    {"name": "phone", "description": "Telefone E.164 com + (ex +5563999368196)", "type": "string"}
])
print("✓ t-profile: headers + query migrados")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Tool: Listar Servicos (t-svc)
#    GET /bot/services  — sem parâmetros de modelo
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-svc"]["parameters"]
fix_headers(p)
print("✓ t-svc: headers migrados (sem query params)")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Tool: Listar Barbeiros (t-brb)
#    GET /bot/barbers  — sem parâmetros de modelo
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-brb"]["parameters"]
fix_headers(p)
print("✓ t-brb: headers migrados (sem query params)")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Tool: Verificar Disponibilidade (t-avail)
#    GET /bot/availability?barber_id=&service_id=&date=
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-avail"]["parameters"]
fix_headers(p)
set_query(p, [
    {"name": "barber_id",   "valueProvider": "modelRequired"},
    {"name": "service_id",  "valueProvider": "modelRequired"},
    {"name": "date",        "valueProvider": "modelRequired"},
])
set_placeholder_defs(p, [
    {"name": "barber_id",  "description": "ID do barbeiro (number)", "type": "number"},
    {"name": "service_id", "description": "ID do servico (number)",  "type": "number"},
    {"name": "date",       "description": "Data YYYY-MM-DD",          "type": "string"},
])
print("✓ t-avail: headers + query migrados (3 params)")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Tool: Cadastrar Cliente (t-cli)
#    POST /bot/clients  body: {phone, name}
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-cli"]["parameters"]
fix_headers(p, with_content_type=True)
set_json_body(
    p,
    body_template='{\n  "phone": "{phone}",\n  "name": "{name}"\n}',
    defs=[
        {"name": "phone", "description": "Numero sem plus (ex 5563999368196)", "type": "string"},
        {"name": "name",  "description": "Nome completo do cliente",            "type": "string"},
    ]
)
print("✓ t-cli: headers + body migrados (phone, name)")

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Tool: Criar Agendamento (t-appt)
#    POST /bot/appointments  body: {client_id, barber_id, service_id, start_at}
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-appt"]["parameters"]
fix_headers(p, with_content_type=True)
set_json_body(
    p,
    body_template=(
        '{\n'
        '  "client_id": {client_id},\n'
        '  "barber_id": {barber_id},\n'
        '  "service_id": {service_id},\n'
        '  "start_at": "{start_at}"\n'
        '}'
    ),
    defs=[
        {"name": "client_id",  "description": "ID do cliente (number)",       "type": "number"},
        {"name": "barber_id",  "description": "ID do barbeiro (number)",      "type": "number"},
        {"name": "service_id", "description": "ID do servico (number)",       "type": "number"},
        {"name": "start_at",   "description": "ISO8601 com fuso -03:00 ex 2026-06-10T09:00:00-03:00", "type": "string"},
    ]
)
print("✓ t-appt: headers + body migrados (4 params)")

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Tool: Consultar Agendamentos (t-lstappt)
#    GET /bot/appointments?phone=+5563...
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-lstappt"]["parameters"]
fix_headers(p)
set_query(p, [{"name": "phone", "valueProvider": "modelRequired"}])
set_placeholder_defs(p, [
    {"name": "phone", "description": "Telefone E.164 com + (ex +5563999368196)", "type": "string"}
])
print("✓ t-lstappt: headers + query migrados")

# ═══════════════════════════════════════════════════════════════════════════════
# 8. Tool: Cancelar Agendamento (t-cancel)
#    PATCH /bot/appointments/{appointment_id}/cancel?phone=+5563...
#    appointment_id está na URL como {placeholder}, phone como query param
# ═══════════════════════════════════════════════════════════════════════════════
p = nodes["t-cancel"]["parameters"]
# URL usa {appointment_id} como path placeholder
p["url"] = "http://host.docker.internal:8000/bot/appointments/{appointment_id}/cancel"
fix_headers(p)
# Remove query params antigos
p.pop("queryParameters", None)
p["specifyQuery"] = "keypair"
p["parametersQuery"] = {"values": [{"name": "phone", "valueProvider": "modelRequired"}]}
set_placeholder_defs(p, [
    {"name": "appointment_id", "description": "ID numerico do agendamento (number)", "type": "number"},
    {"name": "phone",          "description": "Telefone E.164 do cliente com + (ex +5563999368196)", "type": "string"},
])
print("✓ t-cancel: headers + url placeholder + query migrados")

# ─── VERIFICAÇÃO FINAL ────────────────────────────────────────────────────────
print()
print("=== VERIFICAÇÃO FINAL ===")
for tid in ["t-profile","t-svc","t-brb","t-avail","t-cli","t-appt","t-lstappt","t-cancel"]:
    n = nodes[tid]
    p = n["parameters"]
    has_old_header = "headerParameters" in p
    has_new_header = "parametersHeaders" in p
    has_old_query  = "queryParameters" in p
    has_new_query  = "parametersQuery" in p or not p.get("sendQuery")
    has_old_body   = "{{ $fromAI" in p.get("jsonBody", "")
    ok = not has_old_header and has_new_header and not has_old_query
    status = "✓" if ok else "✗"
    print(f"  {status} {n['name']:35} | old-hdr:{has_old_header} new-hdr:{has_new_header} old-qry:{has_old_query} old-$fromAI:{has_old_body}")

with open(ROOT / "workflows.json", "w") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print()
print("✅ workflows.json salvo com schemas corrigidos")
