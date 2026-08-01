"""Versão vigente da política de privacidade (LGPD, D-86).

Todo consentimento gravado carimba a versão que o titular viu no momento do
aceite (`consent_records.policy_version`) — sem isso o histórico prova *que*
alguém consentiu, mas não *com o quê*, que é justamente o que uma fiscalização
pede.

Regra: ao publicar um texto novo em `barbearia-public/app/privacidade/page.tsx`,
subir esta constante **no mesmo commit**. O formato é a data de publicação
(ISO), que ordena sozinha e não exige tabela de versões.
"""

from __future__ import annotations

from typing import Final

PRIVACY_POLICY_VERSION: Final[str] = "2026-07-30"

# Documentos de quem OPERA o sistema (D-87). Mesma regra da política: subir a
# versão no mesmo commit em que o texto muda — aqui isso tem efeito prático
# imediato, porque `..._version_accepted != VERSÃO` reabre o aceite para todo
# mundo no próximo acesso ao painel.
#
# `TERMS` = termo de uso e confidencialidade, aceito por CADA usuário do painel.
# `DPA`   = contrato de operador (LGPD art. 39), aceito UMA VEZ por organização,
#           obrigatoriamente pelo proprietário.
TERMS_VERSION: Final[str] = "2026-07-31"
# 2026-08-01: revisão jurídica do contrato de operador. O termo do funcionário
# não mudou, então `TERMS_VERSION` fica como está — quem já aceitou continua
# aceito; só o DPA volta a ser pedido.
DPA_VERSION: Final[str] = "2026-08-01"

SOURCE_TERMS_ACCEPT: Final[str] = "painel_termo_uso"
SOURCE_DPA_ACCEPT: Final[str] = "painel_contrato_operador"

# Origens de consentimento (`consent_records.source`). Constantes em vez de
# string solta para o backfill/relatório poderem filtrar sem adivinhar grafia.
SOURCE_SITE_SIGNUP: Final[str] = "site_signup"
SOURCE_PANEL_SIGNUP: Final[str] = "painel_cadastro"
SOURCE_CHATBOT: Final[str] = "chatbot_first_contact"
SOURCE_WA_KEYWORD: Final[str] = "wa_keyword"
SOURCE_TRINKS_IMPORT: Final[str] = "trinks_import"
