"""Playbook curado de heurísticas financeiras/de gestão para o insight do Kernel IA
(D-58). Heurísticas GERAIS de mercado para pequenos negócios de serviço (barbearia/
salão) — não são citações de fonte específica; edite/substitua livremente conforme
o gestor tiver referências próprias. Chaves = mesmo enum `topico` da tool
`consultar_financas` (`app.services.kernel_ia_finance.TOPICS`).
"""
from __future__ import annotations

PLAYBOOK: dict[str, list[str]] = {
    "financeiro": [
        "Uma margem líquida saudável (após comissões e despesas) costuma ficar entre "
        "15% e 25% do faturamento em barbearias/salões pequenos; abaixo disso vale "
        "revisar despesas fixas.",
        "Receita muito concentrada em poucos dias da semana é comum no setor — vale "
        "suavizar a demanda com horários ou promoções nos dias mais fracos.",
        "Acompanhar o ticket médio junto do faturamento ajuda a distinguir se o "
        "resultado vem de mais clientes ou de vender mais por atendimento.",
    ],
    "ranking": [
        "Faixas de comissão típicas do setor variam entre 30% e 50% do serviço, a "
        "depender do modelo de trabalho (comissionado, híbrido, aluguel de cadeira).",
        "Grande disparidade de produção entre profissionais costuma indicar espaço "
        "para redistribuir agenda ou investir em capacitação.",
        "Ticket médio bem abaixo da média do time costuma sinalizar oportunidade de "
        "venda adicional (produtos, combos), não necessariamente um problema de volume.",
    ],
    "mrr": [
        "Receita recorrente (assinaturas) costuma ser tratada como o 'piso' garantido "
        "de faturamento do mês, o que ajuda a planejar custo fixo com mais segurança.",
        "Uma fração relevante de assinaturas vencendo nos próximos 30 dias pede ação "
        "de renovação antes que a receita recorrente caia.",
        "Crescimento saudável de MRR normalmente combina captação de novos assinantes "
        "com baixo cancelamento — não só uma das duas frentes.",
    ],
    "folha": [
        "Regra prática comum: manter o custo FIXO da equipe dentro de uma fração "
        "saudável da receita recorrente, evitando depender do caixa do mês pra pagar "
        "salário fixo.",
        "Antes de contratar em CLT (custo fixo), vale checar se o MRR já cobre esse "
        "custo — contratar sobre receita variável aumenta o risco em meses fracos.",
        "Modelos híbridos e aluguel de cadeira reduzem o risco do negócio em troca de "
        "menor controle sobre a agenda do profissional — trade-off comum no setor.",
    ],
    "ia_faturamento": [
        "Atendimentos fechados fora do horário comercial via automação costumam ser "
        "receita que se perderia sem atendimento automatizado — vale olhar a "
        "tendência, não só um período isolado.",
        "Comparar o faturamento do canal automatizado com o faturamento total ajuda a "
        "dimensionar o quanto ele já sustenta do negócio.",
    ],
    "inativos": [
        "Uma janela comum para considerar um cliente 'em risco' em serviços de "
        "beleza/estética é em torno de 45 a 60 dias sem retorno, ajustável ao ciclo "
        "médio de corte/serviço da casa.",
        "Campanhas de reativação com oferta simples tendem a converter melhor quanto "
        "mais cedo são disparadas após o cliente esfriar.",
        "Reativar oferecendo o mesmo profissional preferido costuma converter mais do "
        "que uma oferta genérica.",
    ],
    "buracos": [
        "Horários ociosos concentrados costumam ser a alavanca de receita incremental "
        "mais barata no curto prazo — estrutura e profissional já estão disponíveis.",
        "Divulgar horários vagos de última hora (WhatsApp, lista de espera) é prática "
        "comum para reduzir ociosidade sem depender só de clientes novos.",
        "Ociosidade recorrente no mesmo profissional/horário pode indicar excesso de "
        "capacidade naquele turno — vale considerar ajustar a escala.",
    ],
}
