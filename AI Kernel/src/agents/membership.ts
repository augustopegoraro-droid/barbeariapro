/**
 * agents/membership.ts
 * -----------------------------------------------------------------------------
 * Membership Agent — pacotes, assinaturas e fidelidade (pontos) do cliente.
 *
 * Cliente-facing: responde sobre os PRÓPRIOS dados via WhatsApp e executa
 * renovar/comprar/cancelar/usar/resgatar. Separação de poderes: NÃO emite
 * cobrança (isso é da [[finance-agent]]); renovar/comprar formam um saga com o
 * CRM — se o CRM falhar, compensate() desfaz a operação por completo
 * (cancela a criada E reativa a anterior, no caso de renovação).
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput, Intent, IntentName,
  Membership, PlanStep, RequestContext, ResumeOutcome,
} from '../types';
import { brl, fmtData } from '../kernel/util';
import { resolverServico } from '../tools/agenda.tools';
import {
  DESCONTO_PACOTE, DIAS_ASSINATURA, DIAS_PACOTE, PONTOS_POR_USO, PRECO_ASSINATURA_PADRAO, USOS_PACOTE_PADRAO,
  assinaturaAtiva, cancelarMembership, comprarPacote, criarVoucher, diasParaVencer, economiaTotal,
  pacoteAtivo, pacoteDentroDaValidade, proximoTier, reativarMembership,
  renovarMembership, resgatarPontos, saldoDePontos, saldoUsos, tierAtual, tierParaPontos,
  tierPorNome, usarPacote,
} from '../tools/membership.tools';

type Emit = AgentExecuteInput['emit'];
interface SagaRecord { novoId: string; oldId?: string }

// Payloads opacos do `pending` (o Kernel só os guarda; quem interpreta é o resume()).
type PendResgate = { kind: 'resgate'; pontos: number };
type PendDesambig = { kind: 'desambiguacao'; acao: 'renovar_assinatura' | 'cancelar_assinatura' };
type PendData = PendResgate | PendDesambig;

export class MembershipAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'MembershipAgent',
    description: 'Gerencia pacotes, assinaturas e fidelidade (pontos) do cliente.',
    capabilities: [
      { intent: 'consultar_pacote', description: 'Saldo de usos do pacote e validade' },
      { intent: 'consultar_assinatura', description: 'Status e vencimento da assinatura' },
      { intent: 'consultar_pontos', description: 'Saldo de pontos de fidelidade' },
      { intent: 'consultar_nivel', description: 'Nível atual e quanto falta para o próximo' },
      { intent: 'quanto_economizei', description: 'Economia acumulada com pacotes' },
      { intent: 'renovar_assinatura', description: 'Renovar assinatura/pacote (clona snapshot)' },
      { intent: 'comprar_pacote', description: 'Vender um novo pacote ou assinatura' },
      { intent: 'cancelar_assinatura', description: 'Cancelar assinatura/pacote' },
      { intent: 'usar_pacote', description: 'Dar baixa de um uso do pacote' },
      { intent: 'resgatar_pontos', description: 'Resgatar pontos como crédito de desconto' },
    ],
    permissions: ['membership:read', 'membership:write', 'fidelidade:read', 'fidelidade:write'],
    tools: ['pacoteAtivo', 'assinaturaAtiva', 'saldoDePontos', 'tierAtual', 'comprarPacote', 'renovarMembership', 'cancelarMembership', 'usarPacote', 'resgatarPontos'],
    estimatedCostUsd: 0.0001,
    avgLatencyMs: 90,
    version: '1.0.0',
    health: 'healthy',
  };

  /**
   * Rastreia o que cada step criou/alterou, para a compensação (saga rollback),
   * chaveado por step.id (único por requisição). Mesmo padrão do AgendaAgent
   * (`criadosPorStep`) e do FinanceAgent (`pixPorStep`). A entrada é removida no
   * compensate(); no caminho de sucesso ela persiste — débito conhecido do kernel
   * (estado de saga em memória do agente), a ser resolvido kernel-wide movendo o
   * token de compensação para o RequestContext/StepResult. Não usamos clear() para
   * não apagar o saga de outra requisição sob concorrência.
   */
  private criadosPorStep = new Map<string, SagaRecord>();

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    const { step, context, emit } = input;

    if (!context.customer) {
      return { ok: true, halt: true, reply: 'Para isso eu preciso te identificar — me diz seu nome, por favor 🙂' };
    }
    const cid = context.customer.id;
    const nome = context.customer.name.split(' ')[0];

    switch (step.action) {
      case 'consultar_pacote':
        return this.consultarPacote(cid);
      case 'consultar_assinatura':
        return this.consultarAssinatura(cid);
      case 'consultar_pontos':
        return this.consultarPontos(cid, nome);
      case 'consultar_nivel':
        return this.consultarNivel(step, cid);
      case 'quanto_economizei':
        return this.consultarEconomia(cid, nome);
      case 'usar_pacote':
        return this.usar(cid, emit);
      case 'resgatar_pontos':
        return this.resgatar(step, cid, emit);
      case 'comprar_pacote':
        return this.comprar(step, cid, emit);
      case 'renovar_assinatura':
        return this.renovar(step, cid, emit);
      case 'cancelar_assinatura':
        return this.cancelar(step, cid, emit);
      default:
        return { ok: false, error: `Ação desconhecida: ${step.action}` };
    }
  }

  // --- consultas -----------------------------------------------------------

  private consultarPacote(cid: string): AgentExecuteOutput {
    const m = pacoteAtivo(this.infra, cid);
    if (m) {
      const restante = saldoUsos(m);
      const saldoTxt = restante == null ? 'usos ilimitados' : `${restante} uso(s) restante(s)`;
      return this.ok(`Seu pacote "${m.planName}" tem ${saldoTxt}, válido até ${fmtData(m.endAt)}.`);
    }
    // Distingue "esgotado porém vigente" de "não tem pacote".
    const esgotado = pacoteDentroDaValidade(this.infra, cid);
    if (esgotado) {
      return this.ok(`Seu pacote "${esgotado.planName}" está esgotado (0 usos restantes), válido até ${fmtData(esgotado.endAt)}. Quer comprar outro?`);
    }
    return this.ok('Você não tem pacote ativo no momento. Quer conhecer nossos pacotes?');
  }

  private consultarAssinatura(cid: string): AgentExecuteOutput {
    const m = assinaturaAtiva(this.infra, cid);
    if (!m) return this.ok('Você não tem assinatura ativa. Quer assinar um plano?');
    const dias = diasParaVencer(m);
    const aviso = dias <= 7 ? ' ⚠️ vence em breve!' : '';
    return this.ok(`Sua assinatura "${m.planName}" vence em ${dias} dia(s) (${fmtData(m.endAt)}).${aviso}`);
  }

  private consultarPontos(cid: string, nome: string): AgentExecuteOutput {
    const saldo = saldoDePontos(this.infra, cid);
    const tier = tierAtual(this.infra, cid);
    const nivel = tier ? ` Você está no nível ${tier.name}.` : '';
    return this.ok(`${nome}, você tem ${saldo} ponto(s).${nivel}`);
  }

  private consultarNivel(step: PlanStep, cid: string): AgentExecuteOutput {
    const tier = tierAtual(this.infra, cid);
    const atual = tier ? `Você está no nível ${tier.name}` : 'Você ainda não tem nível';
    const saldo = saldoDePontos(this.infra, cid);

    // Se o cliente perguntou por um nível específico ("falta p/ Ouro"), responde sobre ele.
    const alvo = tierPorNome(this.infra, (step.input as { tier?: string }).tier);
    if (alvo) {
      if (alvo.minPoints > saldo) {
        return this.ok(`${atual}. Faltam ${alvo.minPoints - saldo} ponto(s) para ${alvo.name} (desconto de ${Math.round(alvo.discountPct * 100)}%).`);
      }
      return this.ok(`${atual} — você já alcançou ${alvo.name}. 🎉`);
    }

    const prox = proximoTier(this.infra, cid);
    if (!prox) return this.ok(`${atual} — é o nível máximo! 🏆`);
    return this.ok(`${atual}. Faltam ${prox.faltam} ponto(s) para ${prox.proximo.name} (desconto de ${Math.round(prox.proximo.discountPct * 100)}%).`);
  }

  private consultarEconomia(cid: string, nome: string): AgentExecuteOutput {
    const total = economiaTotal(this.infra, cid);
    if (total <= 0) return this.ok(`${nome}, ainda não há economia registrada — use um pacote e comece a economizar 💈`);
    return this.ok(`${nome}, você já economizou ${brl(total)} usando seus pacotes 💰`);
  }

  // --- ações ---------------------------------------------------------------

  private usar(cid: string, emit: Emit): AgentExecuteOutput {
    // Consome o pacote (vence primeiro) e, se não houver, a assinatura ilimitada.
    const m = pacoteAtivo(this.infra, cid) ?? assinaturaAtiva(this.infra, cid);
    if (!m) return this.ok('Você não tem pacote ou assinatura com saldo para usar agora.');
    const ganhaPontos = m.kind === 'pacote'; // assinatura ilimitada não credita (anti-farming)
    const tierAntes = ganhaPontos ? tierAtual(this.infra, cid)?.name : undefined;
    const r = usarPacote(this.infra, m.id, { ownerId: cid });
    if (!r.ok) return this.ok(r.erro!);
    emit('PackageUsed', { membershipId: m.id, customerId: cid });

    let extra = '';
    if (ganhaPontos) {
      emit('PointsAdded', { customerId: cid, delta: PONTOS_POR_USO, reason: 'uso de pacote' });
      extra = ` (+${PONTOS_POR_USO} pontos)`;
      const tierDepois = tierAtual(this.infra, cid)?.name;
      if (tierAntes && tierDepois && tierAntes !== tierDepois) {
        emit('LevelChanged', { customerId: cid, de: tierAntes, para: tierDepois });
        extra += ` 🎉 Você subiu para o nível ${tierDepois}!`;
      }
    }
    const saldoTxt = r.restante == null ? 'plano ilimitado' : `${r.restante} restante(s)`;
    return this.ok(`Uso registrado no "${m.planName}". Saldo: ${saldoTxt}.${extra}`);
  }

  private resgatar(step: PlanStep, cid: string, emit: Emit): AgentExecuteOutput {
    const args = step.input as { pontos?: string; confirmado?: string };
    const qtd = Number(args.pontos);
    // Sem quantidade: pergunta e deixa o resgate PENDENTE (o Kernel retoma com o número).
    if (!Number.isFinite(qtd) || qtd <= 0) return this.halt('Quantos pontos você quer resgatar?', 0);

    const saldo = saldoDePontos(this.infra, cid);
    if (qtd > saldo) return this.ok(`Saldo insuficiente: você tem ${saldo} ponto(s).`);

    // Prevê rebaixamento de nível ANTES de debitar (ação irreversível → confirma).
    const tierAntes = tierParaPontos(this.infra, saldo);
    const tierDepois = tierParaPontos(this.infra, saldo - qtd);
    const rebaixa = !!tierAntes && !!tierDepois && tierDepois.minPoints < tierAntes.minPoints;
    if (rebaixa && !args.confirmado) {
      // Deixa PENDENTE: o Kernel retoma com "sim"/"confirmar" (sem re-digitar o valor).
      return this.halt(
        `Atenção: resgatar ${qtd} pontos vai te rebaixar de ${tierAntes!.name} para ${tierDepois!.name} (você perde o desconto de ${Math.round(tierAntes!.discountPct * 100)}%). Confirma? Responda "sim" para concluir.`,
        qtd,
      );
    }

    const r = resgatarPontos(this.infra, cid, qtd, 'resgate de desconto');
    if (!r.ok) return this.ok(r.erro!);
    const voucher = criarVoucher(this.infra, cid, qtd, 'resgate de pontos'); // crédito durável (1 ponto = R$1)
    emit('PointsRedeemed', { customerId: cid, delta: -qtd, saldo: r.saldo, voucherId: voucher.id });

    let aviso = '';
    if (rebaixa) {
      emit('LevelChanged', { customerId: cid, de: tierAntes!.name, para: tierDepois!.name });
      aviso = ` ⚠️ Você passou de ${tierAntes!.name} para ${tierDepois!.name}.`;
    }
    return this.ok(`Resgate confirmado: crédito de ${brl(qtd)} registrado para o seu próximo atendimento. Saldo de pontos: ${r.saldo}.${aviso}`);
  }

  private comprar(step: PlanStep, cid: string, emit: Emit): AgentExecuteOutput {
    const args = step.input as { servico?: string; usos?: string; preco?: string; modo?: string };
    const servico = resolverServico(this.infra, args.servico); // reusa o mapeamento canônico

    let r;
    if (args.modo === 'assinatura') {
      const preco = Number(args.preco) > 0 ? Number(args.preco) : PRECO_ASSINATURA_PADRAO;
      r = comprarPacote(this.infra, {
        customerId: cid, planName: `Assinatura ${servico.name}`, kind: 'assinatura',
        serviceIds: [servico.id], includedUses: null, priceBrl: preco, durationDays: DIAS_ASSINATURA, autoRenew: true,
      });
    } else {
      const usos = Number(args.usos) > 0 ? Number(args.usos) : USOS_PACOTE_PADRAO;
      const preco = Number(args.preco) > 0 ? Number(args.preco) : Math.round(servico.priceBrl * usos * (1 - DESCONTO_PACOTE));
      r = comprarPacote(this.infra, {
        customerId: cid, planName: `${usos}× ${servico.name}`,
        serviceIds: [servico.id], includedUses: usos, priceBrl: preco, durationDays: DIAS_PACOTE,
      });
    }
    if (!r.ok) return this.ok(r.erro!, true); // halt: não segue p/ CRM se a venda falhar
    this.criadosPorStep.set(step.id, { novoId: r.membership!.id });
    emit('PackageSold', { membershipId: r.membership!.id, customerId: cid, valor: r.membership!.pricePaidBrl, kind: r.membership!.kind });

    const m = r.membership!;
    const detalhe = m.kind === 'assinatura' ? 'uso ilimitado, renovação automática' : `${m.includedUses} usos, válido ${DIAS_PACOTE} dias`;
    return {
      ok: true,
      output: { membershipId: m.id, valor: m.pricePaidBrl },
      reply: `"${m.planName}" criado por ${brl(m.pricePaidBrl)} (${detalhe}).`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  private renovar(step: PlanStep, cid: string, emit: Emit): AgentExecuteOutput {
    const { alvo, ambiguo } = this.selecionarAlvo(cid, (step.input as { alvo?: string }).alvo);
    if (ambiguo) return this.haltDesambiguacao('Você tem um pacote e uma assinatura ativos. Qual quer renovar — o pacote ou a assinatura?', 'renovar_assinatura');
    if (!alvo) return { ok: true, halt: true, reply: 'Não encontrei assinatura/pacote ativo para renovar. Quer comprar um novo?' };

    const r = renovarMembership(this.infra, alvo.id, cid);
    if (!r.ok) return this.ok(r.erro!, true); // halt: não segue p/ CRM se a renovação falhar
    // Guarda a antiga também: o rollback precisa REATIVÁ-LA (renovar a aposentou).
    this.criadosPorStep.set(step.id, { novoId: r.membership!.id, oldId: alvo.id });
    emit('MembershipRenewed', { de: alvo.id, para: r.membership!.id, customerId: cid });
    return {
      ok: true,
      output: { membershipId: r.membership!.id, valor: r.membership!.pricePaidBrl },
      reply: `Renovado! "${r.membership!.planName}" agora vale até ${fmtData(r.membership!.endAt)}.`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  private cancelar(step: PlanStep, cid: string, emit: Emit): AgentExecuteOutput {
    const { alvo, ambiguo } = this.selecionarAlvo(cid, (step.input as { alvo?: string }).alvo);
    if (ambiguo) return this.haltDesambiguacao('Você tem um pacote e uma assinatura ativos. Qual quer cancelar — o pacote ou a assinatura?', 'cancelar_assinatura');
    if (!alvo) return this.ok('Você não tem assinatura/pacote ativo para cancelar.');
    const r = cancelarMembership(this.infra, alvo.id, 'solicitado pelo cliente', cid);
    if (!r.ok) return this.ok(r.erro!);
    emit('MembershipCancelled', { membershipId: alvo.id, customerId: cid });
    return this.ok(`Cancelado o "${alvo.planName}". Se mudar de ideia, é só assinar de novo. 🙏`);
  }

  /**
   * Seleciona a membership alvo respeitando o tipo nomeado pelo cliente. Em ação
   * destrutiva, NÃO cai para o outro tipo: "cancelar meu pacote" nunca cancela a
   * assinatura. O fallback cruzado só vale no pedido genérico (tipo indefinido).
   */
  private selecionarAlvo(cid: string, tipo?: string): { alvo?: Membership; ambiguo?: boolean } {
    const pac = pacoteAtivo(this.infra, cid);
    const ass = assinaturaAtiva(this.infra, cid);
    if (tipo === 'pacote') return { alvo: pac };
    if (tipo === 'assinatura') return { alvo: ass };
    if (pac && ass) return { ambiguo: true }; // pedido genérico com ambos ativos → pergunta
    return { alvo: ass ?? pac };
  }

  /** Compensação (saga): desfaz a operação por completo se um passo seguinte falhar. */
  async compensate(step: PlanStep, ctx: RequestContext): Promise<void> {
    const rec = this.criadosPorStep.get(step.id);
    if (!rec) return;
    const owner = ctx.customer?.id;
    cancelarMembership(this.infra, rec.novoId, 'rollback (saga)', owner); // desfaz a criada
    if (rec.oldId) reativarMembership(this.infra, rec.oldId, owner); // restaura a anterior (renovação)
    this.criadosPorStep.delete(step.id);
  }

  private ok(reply: string, halt = false): AgentExecuteOutput {
    return { ok: true, reply, halt, costUsd: this.descriptor.estimatedCostUsd };
  }

  /** Halt que registra um resgate pendente — o Kernel guarda e devolve no resume(). */
  private halt(reply: string, pontos: number): AgentExecuteOutput {
    return this.haltCom(reply, { kind: 'resgate', pontos });
  }

  /** Halt de esclarecimento (pacote ou assinatura?). */
  private haltDesambiguacao(reply: string, acao: 'renovar_assinatura' | 'cancelar_assinatura'): AgentExecuteOutput {
    return this.haltCom(reply, { kind: 'desambiguacao', acao });
  }

  private haltCom(reply: string, data: PendData): AgentExecuteOutput {
    // pending opaco para o Kernel: { agent, data } — só o resume() abaixo interpreta `data`.
    return {
      ok: true, halt: true, reply,
      output: { pending: { agent: this.descriptor.name, data } },
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  /**
   * Interpreta a resposta do cliente a uma pergunta pendente que ESTE agente criou
   * (confirmação de resgate ou desambiguação pacote/assinatura). Toda a regra de
   * domínio do multi-turn vive aqui — o Kernel apenas roteia.
   */
  resume(pending: unknown, text: string): ResumeOutcome {
    const p = pending as PendData;
    const t = text.toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '').trim();

    // --- Esclarecimento: pacote ou assinatura? ---
    if (p.kind === 'desambiguacao') {
      if (/pacote/.test(t)) return this.intentDe(p.acao, { alvo: 'pacote' });
      if (/assinatura|mensalidade|plano/.test(t)) return this.intentDe(p.acao, { alvo: 'assinatura' });
      return { reprompt: 'Não entendi 🙂 Você quer o *pacote* ou a *assinatura*?' };
    }

    // --- Confirmação de resgate que rebaixa o nível (ação irreversível) ---
    // Negação em QUALQUER posição cancela (segurança: nunca confirmar sob recusa).
    if (/\bnao\b|\bnunca\b|cancel|deixa|esquec|absurdo/.test(t)) return 'cancelado';

    const aguardandoConfirmacao = p.pontos > 0;
    const num = t.match(/(\d{1,5})/); // um número (mesmo dentro de frase) = montante pedido
    const afirma = /\b(sim|confirmo|confirmar|confirmado|aceito|ok|isso mesmo|pode confirmar|pode ser|quero sim)\b/.test(t);

    let pontos: number;
    let confirmado = false;
    if (num) {
      pontos = Number(num[1]);
      // só é confirmação se RE-DIGITOU o mesmo valor pendente; valor diferente = novo pedido.
      confirmado = aguardandoConfirmacao && pontos === p.pontos;
    } else if (afirma && aguardandoConfirmacao) {
      pontos = p.pontos;
      confirmado = true;
    } else {
      // resposta não inequívoca → re-pergunta MANTENDO o pendente (não descarta em silêncio).
      return {
        reprompt: aguardandoConfirmacao
          ? `Não entendi. Quer confirmar o resgate de ${p.pontos} pontos? Responda *sim* ou *não*.`
          : 'Quantos pontos você quer resgatar?',
      };
    }
    return this.intentDe('resgatar_pontos', confirmado ? { pontos: String(pontos), confirmado: '1' } : { pontos: String(pontos) });
  }

  private intentDe(name: IntentName, entities: Record<string, string>): Intent {
    return { name, confidence: 0.9, urgency: 'media', sentiment: 'neutro', locale: 'pt-BR', entities };
  }
}
