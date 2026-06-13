"""
Testes T-07 a T-12 do checklist de estabilização.
Execução: python scripts/test_t07_t12.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, json, uuid

BASE = "http://localhost:8000"
TOKEN = os.environ.get("BOT_API_KEY")
if not TOKEN:
    sys.exit("Defina BOT_API_KEY no ambiente antes de rodar este script.")
HDR = {"X-Bot-Token": TOKEN, "Content-Type": "application/json"}
PHONE = "+5511900000099"

passed = []
failed = []

def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"PASSOU | {name}" + (f" | {detail}" if detail else ""))
    else:
        failed.append(name)
        print(f"FALHOU | {name}" + (f" | {detail}" if detail else ""))

def flush(phone=PHONE):
    r = requests.post(f"{BASE}/bot/debounce/flush", headers=HDR, json={"phone": phone})
    return r.json()

def debounce(phone, msg, mid):
    r = requests.post(f"{BASE}/bot/debounce", headers=HDR,
                      json={"phone": phone, "message": msg, "message_id": mid})
    return r.json()

# T-07: Mensagens enviadas em partes (rajada)
print("\n══ T-07: MENSAGENS EM PARTES (rajada) ══")
flush(PHONE)  # limpar buffer
# IDs únicos por execução para evitar falsos positivos em _seen_ids
uid = str(uuid.uuid4())[:8]
r1 = debounce(PHONE, "oi", f"t07-a-{uid}")
r2 = debounce(PHONE, "quero cortar", f"t07-b-{uid}")
r3 = debounce(PHONE, "com o Taylor", f"t07-c-{uid}")
check("T-07.1 primeira msg é controller", r1["proceed"] is True, f"proceed={r1['proceed']}")
check("T-07.2 segunda msg não é controller", r2["proceed"] is False, f"proceed={r2['proceed']}")
check("T-07.3 terceira msg não é controller", r3["proceed"] is False, f"proceed={r3['proceed']}")
fl = flush(PHONE)
all_msgs = fl.get("message", "")
check("T-07.4 flush concatena todas",
      all([x in all_msgs for x in ["oi", "cortar", "Taylor"]]),
      f"msg='{all_msgs}'")

# T-08: Mensagem duplicada (re-delivery)
print("\n══ T-08: MENSAGEM DUPLICADA (re-delivery) ══")
flush(PHONE)
uid08 = f"UNIQUE-T08-{str(uuid.uuid4())[:8]}"
r_first = debounce(PHONE, "ola", uid08)
flush(PHONE)  # processar
r_redeliv = debounce(PHONE, "ola", uid08)
check("T-08.1 primeira entrega proceed=True", r_first["proceed"] is True, f"proceed={r_first['proceed']}")
check("T-08.2 re-delivery ignorado", r_redeliv["proceed"] is False, f"proceed={r_redeliv['proceed']}")

# T-09: Sessão expirada (nova sessão detectada)
print("\n══ T-09: SESSÃO APÓS SILÊNCIO ══")
uid09 = str(uuid.uuid4())[:8]
# Simular último flush 5h atrás via endpoint de debug (SESSION_GAP=4h)
r_debug = requests.post(f"{BASE}/bot/debounce/debug-set-session", headers=HDR,
    json={"phone": PHONE, "minutes_ago": 300})
check("T-09.0 debug endpoint respondeu", r_debug.status_code == 200, f"HTTP {r_debug.status_code}")
r_new = debounce(PHONE, "voltei", f"t09-new-{uid09}")
check("T-09.1 sessão nova detectada", r_new["is_new_session"] is True, f"is_new_session={r_new['is_new_session']}")
fl9 = flush(PHONE)
check("T-09.2 flush propaga is_new_session", fl9["is_new_session"] is True, f"is_new_session={fl9['is_new_session']}")

# T-10: Fora do horário comercial → bloqueio
print("\n══ T-10: FORA DO HORÁRIO COMERCIAL ══")
import subprocess
result = subprocess.run(["node", "-e", """
function checkHorario(utcTs, bypass) {
  const palmasMs = utcTs + (-3 * 3600 * 1000);
  const palmas = new Date(palmasMs);
  const hour = palmas.getUTCHours();
  const day = palmas.getUTCDay();
  let isOpen = bypass;
  if (!bypass) {
    if (day >= 1 && day <= 5) isOpen = hour >= 9 && hour < 19;
    else if (day === 6) isOpen = hour >= 9 && hour < 17;
  }
  return isOpen;
}
// Dom 14h Palmas = UTC 17h
const sunTs = new Date('2026-06-07T17:00:00Z').getTime();
// Qui 14h Palmas = UTC 17h
const thuTs = new Date('2026-06-04T17:00:00Z').getTime();
// Qui 23h Palmas = UTC+1 = dom na madrugada
const lateTs = new Date('2026-06-05T02:00:00Z').getTime();

console.log('sun_open:', checkHorario(sunTs, false));  // false
console.log('thu_open:', checkHorario(thuTs, false));  // true
console.log('late_open:', checkHorario(lateTs, false)); // false
console.log('bypass_true:', checkHorario(sunTs, true)); // true
"""], capture_output=True, text=True)
lines = {l.split(':')[0].strip(): l.split(':')[1].strip() for l in result.stdout.strip().split('\n') if ':' in l}
check("T-10.1 domingo fechado com BYPASS=false", lines.get("sun_open") == "false", f"isOpen={lines.get('sun_open')}")
check("T-10.2 quinta aberto com BYPASS=false", lines.get("thu_open") == "true", f"isOpen={lines.get('thu_open')}")
check("T-10.3 madrugada fechado com BYPASS=false", lines.get("late_open") == "false", f"isOpen={lines.get('late_open')}")
check("T-10.4 BYPASS=true ignora horário", lines.get("bypass_true") == "true", f"isOpen={lines.get('bypass_true')}")

# T-10.5 BYPASS_HOURS=false no workflow instalado
import json as _json
with open("workflows.json") as f:
    wf_data = _json.load(f)
bot_wf = next(w for w in wf_data if "BarbeariaPro Bot" in w.get("name",""))
hora = next(n for n in bot_wf["nodes"] if n["id"] == "hora-001")
bypass_false = "BYPASS_HOURS = false" in hora["parameters"]["jsCode"]
check("T-10.5 BYPASS_HOURS=false no workflow", bypass_false)

# T-11: Áudio → mensagem descritiva
print("\n══ T-11: ÁUDIO ══")
set_phone = next(n for n in bot_wf["nodes"] if n["id"] == "setphone-001")
msg_assign = next(a for a in set_phone["parameters"]["assignments"]["assignments"] if a["name"] == "message")
audio_handled = "audioMessage" in msg_assign["value"] and "áudio" in msg_assign["value"]
check("T-11.1 audioMessage tratado no Set Phone", audio_handled, msg_assign["value"][:60])

# T-12: Imagem com legenda
print("\n══ T-12: IMAGEM ══")
image_handled = "imageMessage" in msg_assign["value"] and "caption" in msg_assign["value"]
check("T-12.1 imageMessage tratado no Set Phone", image_handled, msg_assign["value"][:60])

# T-04c: Horário não alinhado rejeitado pelo backend
print("\n══ T-04c: HORÁRIO NÃO ALINHADO ══")
r_bad = requests.post(f"{BASE}/bot/appointments", headers=HDR,
    json={"client_id":10,"barber_id":1,"service_id":1,"start_at":"2026-06-08T09:03:00-03:00"})
check("T-04c.1 9:03 rejeitado (422)", r_bad.status_code == 422, f"HTTP {r_bad.status_code}")

r_dom = requests.post(f"{BASE}/bot/appointments", headers=HDR,
    json={"client_id":10,"barber_id":1,"service_id":1,"start_at":"2026-06-07T09:00:00-03:00"})
check("T-04c.2 domingo rejeitado (422)", r_dom.status_code == 422, f"HTTP {r_dom.status_code}")

r_noite = requests.post(f"{BASE}/bot/appointments", headers=HDR,
    json={"client_id":10,"barber_id":1,"service_id":1,"start_at":"2026-06-08T23:00:00-03:00"})
check("T-04c.3 23h rejeitado (422)", r_noite.status_code == 422, f"HTTP {r_noite.status_code}")

# T-05b: Ownership check — outro cliente NÃO pode cancelar
print("\n══ T-05b: OWNERSHIP CHECK ══")
# Criar agendamento para cliente 10
r_new_appt = requests.post(f"{BASE}/bot/appointments", headers=HDR,
    json={"client_id":10,"barber_id":1,"service_id":1,"start_at":"2026-06-08T11:00:00-03:00"})
appt_id = r_new_appt.json().get("id")

# Tentar cancelar com telefone de outro cliente
r_wrong = requests.patch(f"{BASE}/bot/appointments/{appt_id}/cancel?phone=%2B5511999999999", headers=HDR)
check("T-05b.1 outro cliente recebe 404", r_wrong.status_code == 404, f"HTTP {r_wrong.status_code}")

# Cancelar com telefone correto
r_right = requests.patch(f"{BASE}/bot/appointments/{appt_id}/cancel?phone=%2B5511900000099", headers=HDR)
check("T-05b.2 dono cancela OK (200)", r_right.status_code == 200, f"HTTP {r_right.status_code}")

print(f"\n{'='*50}")
print(f"RESULTADO FINAL: {len(passed)} PASSOU | {len(failed)} FALHOU")
if failed:
    print(f"\nFALHARAM: {', '.join(failed)}")
sys.exit(0 if not failed else 1)
