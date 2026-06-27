# Fase 0 — WhatsApp Cloud API (Meta): pré-requisitos e checklist

> Passo a passo para habilitar o **WhatsApp Cloud API oficial** com um **número novo dedicado**,
> destino do canal WhatsApp do Chatwoot (D-49). **É o gargalo de prazo** (verificação Meta leva dias) e
> **bloqueia as Fases 2/3/4** — começar já, em paralelo ao resto.
>
> Caminho escolhido: **direto na Meta** (canal nativo "WhatsApp Cloud" do Chatwoot; mais barato que BSP).
> Data: 2026-06-27.

---

## 0. Antes de tudo — o número

- [ ] **Número NOVO dedicado** ao bot. **NÃO** reusar o `5563920001734` (restrito — D-41) nem um número
      que já esteja ativo no app WhatsApp/WhatsApp Business comum.
- [ ] O número precisa **receber SMS ou ligação** (código de verificação da Meta).
- [ ] Se o número já tiver uma conta WhatsApp, **desvincular/excluir** essa conta antes (um número só pode
      estar na Cloud API **ou** no app, não nos dois).
- [ ] Decidir o **nome de exibição** (display name) — segue as regras da Meta (sem termos proibidos;
      coerente com a marca "Taylor & Thedy").

## 1. Conta e verificação de negócio (o passo lento — fazer 1º)

- [ ] Ter/confirmar um **Meta Business Account** em `business.facebook.com` (Gerenciador de Negócios).
- [ ] Iniciar a **Verificação de Negócio** (Configurações do negócio → Central de Segurança):
      exige documento da empresa (**CNPJ**, comprovante etc.). **Leva dias** — iniciar imediatamente.
- [ ] Sem verificação você fica num **tier limitado** (poucas conversas/dia, número de destinatários
      restrito). Verificado = sobe os limites e libera produção.

## 2. App Meta + produto WhatsApp

- [ ] Em `developers.facebook.com` → **Criar App** → tipo **Business**.
- [ ] Adicionar o produto **WhatsApp** ao app. Isso cria automaticamente:
      - um **número de teste** (descartável, só p/ sandbox);
      - uma **WhatsApp Business Account (WABA)**.
- [ ] Em **WhatsApp → Configuração da API** (ou WhatsApp Manager), **adicionar o número novo real** e
      **verificá-lo** por SMS/ligação.

## 3. Credenciais que o Chatwoot vai pedir (anotar com segurança)

O canal "WhatsApp Cloud" do Chatwoot pede estes 4 itens:

- [ ] **Phone Number ID** (do número novo) — em WhatsApp Manager.
- [ ] **WhatsApp Business Account ID (WABA ID)**.
- [ ] **Token de acesso PERMANENTE** — o token inicial **expira em 24h**; criar um permanente:
      - Business Settings → **Usuários do sistema** → criar um System User (admin);
      - **atribuir o ativo** WABA a esse usuário;
      - **gerar token** com as permissões **`whatsapp_business_messaging`** e
        **`whatsapp_business_management`**.
- [ ] **API key / verify token do webhook** — string secreta que você define; será colada nos dois lados
      (Meta e Chatwoot) na **Fase 2**.

> ⚠️ Esses são **segredos** (regra §5 do `CLAUDE.md`): guardar fora do git, só em `.env`/cofre.

## 4. Webhook — **só na Fase 2** (depende do Chatwoot no ar)

- [ ] Adiar: o **callback URL** do webhook vem do Chatwoot quando você cria o canal (Fase 2). Aí você cola
      esse URL + o verify token no app Meta (**WhatsApp → Configuração → Webhook**) e **assina o campo
      `messages`**. Não dá para concluir agora porque o domínio HTTPS do Chatwoot ainda não existe.

## 5. Templates de mensagem (pode adiantar assim que a WABA existir)

Mensagens **proativas / fora da janela de 24h** (lembrete 24h, reativação) **exigem template aprovado**.

- [ ] Em **WhatsApp Manager → Modelos de mensagem**, criar e **submeter à aprovação**:
      - **Lembrete de agendamento** (categoria *Utility*) — com variáveis (nome, data/hora, serviço).
      - **Reativação de cliente** (categoria *Marketing* — regras mais rígidas, pode ter mais recusa).
- [ ] Aprovação leva de minutos a ~1 dia. Mapear **todos** os disparos proativos atuais
      (`reminders.py`/`reactivation.py`) para um template equivalente.

## 6. Faturamento

- [ ] Adicionar **forma de pagamento** à WABA (a Cloud API cobra **por conversa**; há cota grátis de
      conversas de *serviço*, mas templates *utility/marketing* são tarifados).
- [ ] Configurar limite de gasto/alertas para não tomar susto.

---

## Resultado esperado da Fase 0 (aceite)

- [ ] Negócio **verificado** na Meta (ou ao menos submetido e operando no tier inicial).
- [ ] Número novo **verificado** e ativo na Cloud API.
- [ ] **Phone Number ID + WABA ID + token permanente** guardados em segredo.
- [ ] Templates de lembrete/reativação **submetidos** (idealmente aprovados).
- [ ] Forma de pagamento ativa.
- [ ] (Webhook fica pendente para a Fase 2.)

## Dependências entre fases
```
F0 (Meta — dias)  ─────────────► credenciais + número
                                      │
F1 (VM + Chatwoot + HTTPS) ───────────┤
                                      ▼
F2 (canal WhatsApp Cloud no Chatwoot) ── aqui se fecha o WEBHOOK na Meta
                                      ▼
F3 (Raquel Agent Bot) → F4 (glue funil) → F5 (cutover)
```

## Se um dia optar por BSP (alternativa, não escolhida)
- **360dialog** é o BSP mais usado com Chatwoot (canal próprio). Simplifica token/templates, mas cobra
  mensalidade + por conversa. Trocaria os passos 2–3 (você usaria o painel do BSP em vez do app Meta).
- Reavaliar só se a gestão do app Meta/tokens virar fricção real.
