# Auditoria — Fase 0 do Site Público de Agendamento do Cliente Final

> Origem: `promptsitepublico.md`. Iniciativa irmã de `promptseguranca.md` (Fases 0-6 já em produção — RBAC,
> auditoria, painel de segurança, `client_visibility_settings`). Esta é a **Fase 0 (descoberta e auditoria)**:
> leitura/pesquisa, sem código. **Checkpoint obrigatório — aguardando aprovação explícita antes da Fase 1
> (Arquitetura).**
>
> Data: 2026-07-17.

---

## 1. Estado atual real

**Confirmado: não existe nenhum site público hoje.** Não há `app/api/public.py` nem qualquer rota sem
autenticação voltada ao cliente final (busca em todo o repo, sem resultado). O único endpoint público
correlato é `GET /auth/tenant` (`app/api/auth.py:137-165`), que resolve org por subdomínio para o **login do
painel administrativo** — não serve ao cliente final. A própria docstring da migration `0041`
(`client_visibility_settings`) já registra isso por escrito, e bate com a confirmação da Fase 0 do
`promptseguranca.md`. Nada mudou desde então.

### Peças reaproveitáveis, prontas hoje

| Peça | Onde | Estado |
|---|---|---|
| `client_visibility_settings` (D-73) | `models/client_visibility.py:21-39`, migration `0041` | 1 linha por org (RLS+FORCE). `services`/`professionals` (JSONB, `{"mode": "all"|"custom", "ids": []}`), `show_hours`/`show_reviews`/`show_promotions` (bool), `banner` (JSONB: enabled/image_url/title/subtitle/cta), `public_info` (JSONB: address/phone/whatsapp/instagram/website). **Sem `logo_url` dedicado** — só `banner.image_url`. Já cobre tudo que o site precisa exibir; falta só o endpoint público de leitura. |
| `Client.phone_e164` | `models/client.py:36-86` | `UNIQUE(organization_id, phone_e164)` + CHECK regex E.164. Chave de identidade pronta, mas **unicidade é por org** — o mesmo telefone em N tenants gera N registros `Client` distintos. Sem conceito de "conta" cross-tenant. |
| `normalize_phone`/`mask_phone` | `app/core/phone.py:10-41` | Assume Brasil (+55), já usado no import Trinks. Reusar como está. |
| Resolução de subdomínio pré-tenant | `app/services/tenant.py::org_id_by_subdomain` + `app_org_id_by_subdomain` (SECURITY DEFINER, migration `0020`) | Molde comprovado em produção em `GET /auth/tenant`. Replicar exatamente o mesmo padrão para o(s) endpoint(s) público(s) novo(s). |
| Redis (D-68) | `app/core/config.py:20-31`, isolado do Redis do Evolution | Já usado para rate-limit/lockout de login e denylist de JWT (slowapi). Reusável para rate-limit de OTP e cache do `GET /public/{subdomain}/info`. |
| `audit_logs`/`record_event` (D-70) | `app/services/audit.py:135-166` | `actor_kind` já é campo livre (hoje `"user"`) — auditar ações do cliente final (`actor_kind="client"`) não exige mudança estrutural. |
| `barber_has_conflict` | `app/services/scheduling.py:18-49` | Reusável como validação final de qualquer criação de agendamento nova, incluindo a do site público. |

### Peças que exigem construção nova (padrão replicável, não a peça em si)

- **Sessões de longa duração**: `sessions` (D-68, migration `0038`) está acoplada a `users`/senha/RBAC de
  staff — a tabela não serve para `Client` (sem senha, sem role). O **padrão** (hash do refresh + rotação +
  detecção de reuso + lookup pré-tenant via função SECURITY DEFINER, igual `app_org_id_by_refresh_hash`) é
  diretamente replicável para uma tabela nova `client_sessions`.
- **Horários disponíveis (slots livres)**: hoje `scheduling.py` só faz detecção reativa de conflito na
  criação — não existe nenhum cálculo de "quais horários estão livres" por serviço×profissional×dia. Precisa
  nascer do zero em `app/services/`, para reúso pelo painel/bot também (como o próprio prompt já antecipa).
- **WhatsApp Cloud API oficial**: `app/services/whatsapp.py` é **100% Evolution API** (não-oficial, via QR) —
  zero código para a Cloud API oficial da Meta. Isso é o bloqueio de caminho crítico da seção 3.

---

## 2. Pesquisa técnica de sessão persistente em mobile web (risco nº 1 do projeto)

Fontes primárias (WebKit/Apple, MDN, Chromium, RFC 9700/IETF, OWASP, Auth0/Okta) consultadas em 2026-07-16.

### iOS Safari — Intelligent Tracking Prevention (ITP)

- **O cap de 7 dias de inatividade continua vigente**, confirmado pela própria página de referência viva da
  WebKit (webkit.org/tracking-prevention, alta confiança): todo "script-writable storage"
  (localStorage/IndexedDB/sessionStorage/cache de Service Worker/cookies JS) de um site aberto como aba
  comum do Safari é apagado após 7 dias sem interação do usuário **com aquela página**.
- **PWA instalado (modo standalone, "Adicionar à Tela de Início") é explicitamente isento** desse cap — a
  própria WebKit trata apagamento nesse caso como bug (webkit.org/blog/10218, alta confiança). O storage do
  PWA instalado é isolado do Safari solto (dados não são compartilhados entre os dois).
- Cookie definido pelo **servidor** (`Set-Cookie`, first-party, mesmo IP, sem CNAME cloaking) pode durar até
  400 dias mesmo fora do modo instalado — mas ainda sujeito à mesma purga por inatividade de 7 dias e a
  reclassificação anti-tracking da Apple (Safari 16.4+). **Não é garantia equivalente ao PWA instalado.**
- iOS 26 (2025/2026) passou a tratar por padrão qualquer site adicionado à Tela de Início como "web app"
  standalone, ampliando quem ganha a isenção — mas esta informação vem de imprensa técnica (MacRumors), não
  de doc oficial Apple/WebKit (confiança média).

### Android Chrome

- **Sem cap por calendário.** O único mecanismo é eviction reativa por pressão de disco (LRU), documentado
  pela própria MDN contrastando explicitamente com o comportamento do Safari (alta confiança). PWAs
  instaladas (ou sites com alto "site engagement score") têm prioridade de sobrevivência sob pressão de
  disco, mas isso não é sobre expiração por tempo.

### Refresh token de vida longuíssima — padrão da indústria

- RFC 9700 (OAuth 2.0 Security BCP, jan/2025, alta confiança): padrão é **rotação a cada uso** + detecção de
  reuso + revogação de toda a linhagem/família ao detectar token já invalidado reaparecendo — não um token
  fixo de duração infinita.
- Esse é **exatamente o padrão que o D-68 já implementa** para staff (`sessions`, migration `0038`: access
  15min + refresh rotativo 30 dias + `prev_refresh_token_hash` para detecção de reuso + revogação de sessão
  inteira). A Fase 2 deve replicar essa arquitetura para `Client`, só com expiração absoluta muito mais longa
  — não reinventar.
- OWASP (alta confiança): nunca guardar tokens em localStorage/sessionStorage (XSS); preferir cookies
  HttpOnly+Secure+SameSite.

### Benchmark de mercado (Booksy, Fresha, Trinks, iFood, Uber)

- Todos oferecem **app nativo dedicado ao consumidor final**, além de (ou em vez de) acesso web. Nenhum
  relato público de engenharia liga isso explicitamente ao ITP — é inferência bem fundamentada em fonte
  primária Apple/WebKit, não confirmação direta das empresas.
- iFood testou PWA opcional (2019) com motivação declarada de economia de espaço em Android, não persistência
  de sessão no iOS.

### Conclusão de risco (a levar para decisão na Fase 1)

**A promessa "nunca mais loga no mesmo aparelho" só é tecnicamente garantível se o cliente instalar o site
como PWA.** Em Safari aberto solto, um cookie de servidor de longa duração é o melhor esforço possível, mas
finito (7 dias de inatividade real, ou reclassificação anti-tracking). A Fase 1 precisa decidir
explicitamente entre: (a) insistir/forçar a instalação como PWA no primeiro acesso, com fallback de re-login
tolerável em quem recusar, ou (b) aceitar re-login ocasional no Safari não instalado como comportamento
padrão para uma fração dos usuários. **Não fingir que "salvar num cookie" resolve — não resolve
sozinho.**

---

## 3. Fluxo de OTP via WhatsApp

- Confirmado no código: hoje só existe Evolution API (`app/services/whatsapp.py`, número restrito D-41). Zero
  linha de código para WhatsApp Cloud API oficial da Meta.
- Cloud API oficial (se adotada): mensagens de template categoria **Authentication** têm texto fixo (não
  customizável além de variáveis), exigem aprovação prévia da Meta, suportam autofill (zero-tap Android /
  one-tap / copy-code; iOS 26+ ganhou autofill nativo via teclado). Custo por mensagem é baixo (ordem de
  US$ 0,0068, a confirmar no rate card oficial — não foi possível extrair o CSV/PDF primário, tratar como
  estimativa). Tiers de volume diário (250 → 2.000 → 10.000 → 100.000 → ilimitado, compartilhado por
  portfólio) folgam de sobra para uma barbearia pequena desde o dia 1.
- **Bloqueio de caminho crítico, já sinalizado no próprio `promptsitepublico.md` (item 1 das "Melhorias
  incorporadas"), e esta pesquisa confirma que segue aberto**: sem resolver isso, a Fase 2 (núcleo de
  autenticação) não pode começar. Duas saídas possíveis, a decidir explicitamente na Fase 1:
  1. Tratar a Fase 0 do plano Chatwoot/Cloud API (D-49) como pré-requisito deste site (número novo dedicado).
  2. Especificar fallback de OTP via **SMS** (Twilio/Zenvia, ~R$0,10/envio) enquanto o Cloud API não sai do
     papel.

---

## 4. Benchmark de UX (nota curta — detalhamento fica para a Fase 1/wireframes)

Booksy, Trinks e Fresha operam com app nativo + web, fluxo de primeiro acesso por telefone é padrão do
mercado consumidor de agendamento de serviços no Brasil e fora. Não há evidência pública de que algum desses
concorrentes "nunca pede login de novo" no site aberto solto no Safari — reforça a conclusão da seção 2 de
que essa promessa depende de instalação como PWA. Wireframes e comparação tela a tela (home, escolha de
serviço/profissional/horário, confirmação) ficam para a Fase 1, quando a decisão de sessão já estiver
fechada.

---

## 5. Matriz de risco

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Safari muda comportamento de ITP numa atualização (histórico: já mudou várias vezes) | Média | Alto (quebra a promessa central) | Não depender só de cookie; PWA instalado é a única garantia documentada hoje; monitorar release notes WebKit; fallback de re-login tolerável já desenhado desde a Fase 1 |
| Usuário limpa cache do navegador / desinstala | Baixa-média | Baixo | Comportamento aceito por design (re-OTP), não é falha do sistema — comunicar isso na UX |
| OTP via Evolution API instável/bloqueado (D-41 já mostrou restrição) | Alta (é o estado atual confirmado) | Crítico (bloqueia toda a Fase 2) | Decisão obrigatória na Fase 1: Cloud API oficial (pré-requisito) vs. SMS de fallback — não iniciar Fase 2 sem isso resolvido |
| Refresh token de longa duração furtado | Baixa | Alto (sessão de cliente comprometida por muito tempo) | Replicar o padrão do D-68: rotação + detecção de reuso + revogação de família + tela "meus dispositivos" para revogação manual |
| Mesmo telefone existe em múltiplos tenants (unicidade de `Client.phone_e164` é por org) | Certa (é o modelo hoje) | Baixo, se documentado | Sessão de cliente final escopada por org — sem conceito de "conta" cross-tenant. Documentar como limitação consciente do modelo atual, não como bug a corrigir nesta iniciativa |
| Rate limit/aprovação de template da Meta atrasar o lançamento | Média | Médio | Iniciar processo de aprovação de template de autenticação cedo, em paralelo à Fase 1/2, não deixar para a Fase 5 |

---

## Conclusão da Fase 0

Estado do código confirmado (nada de site público existe; peças reaproveitáveis mapeadas com precisão de
arquivo:linha). Risco técnico central (sessão persistente) pesquisado com fontes primárias e veredito claro:
**PWA instalado é necessário para a garantia forte; sem isso, é best-effort com fallback**. Bloqueio de
caminho crítico do OTP via WhatsApp confirmado e não resolvido — precisa de decisão explícita na Fase 1 antes
da Fase 2 começar.

**Aguardando aprovação explícita para avançar à Fase 1 (Arquitetura — `ARQUITETURA_SITE_PUBLICO.md`).**
