# TODO — Painel SuperAdmin + Billing

> Espelho de trabalho da missão (ordem = prioridade). Detalhe das milestones em `roadmap.md`.

## Agora
- [ ] M8: endpoints de plataforma de billing (planos CRUD+sync, assinaturas c/ dunning,
      cupons, créditos, webhook-events+reprocess) + telas do painel (/assinaturas,
      /financeiro, /configuracoes→planos) + Minha Assinatura no tenant (/admin/empresa)

## Fila
- [ ] M9: `GET /platform/alerts` + Central de Operações · `platform_audit_log`
- [ ] M10: impersonation (token curto com motivo + auditoria + banner no tenant)
- [ ] M11: configurações da plataforma (regras de alerta; planos já em M8)
- [ ] MF: hardening + suíte verde + docs finais + CLAUDE.md/DECISIONS.md (entrada D-6x)

## Follow-ups técnicos (deliberados)
- [ ] Espelhar cupom na Stripe (`provider_discount_id`) — hoje desconto é local
- [ ] "Dias grátis" com gateway estende só o período local (`provider_extended:false`
      no evento) — desconto real via cupom
- [ ] Investigar flake de ordenação `test_membership_integration::test_venda_personalizada_do_zero`
      (passa isolado e em par com billing; falhou 1× na suíte completa pós-M7)
- [ ] `usage_metrics`: popular contadores mensais (mensagens bot) p/ limites de uso
- [ ] MF: revisar `tenants_membership_mrr` O(N) (função SD agregada)

## Concluído
- [x] M1 análise + architecture.md · M2 shell/⌘K/patterns · M3 metrics+dashboard ·
      M4 tabela rica · M5 detalhe 360° · M6 onboarding · M7 billing core (2026-07-03)
- [x] Migrations staging: head `0032` · suíte 437 pass (2026-07-03)
