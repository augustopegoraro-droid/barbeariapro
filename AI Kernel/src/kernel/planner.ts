/**
 * kernel/planner.ts
 * -----------------------------------------------------------------------------
 * Planner — transforma uma solicitação em um plano de execução.
 *
 * Para as intenções conhecidas da barbearia, usa modelos de plano
 * determinísticos (mais barato e auditável). Um pedido pode envolver vários
 * agentes, com dependências entre passos.
 * -----------------------------------------------------------------------------
 */

import { ExecutionPlan, PlanStep, RequestContext } from '../types';
import { id } from './util';

function step(p: Omit<PlanStep, 'id'>): PlanStep {
  return { id: id('step'), ...p };
}

export class Planner {
  plan(ctx: RequestContext): ExecutionPlan {
    const { intent } = ctx;
    const ent = intent.entities;

    switch (intent.name) {
      case 'consultar_horarios':
        return {
          goal: 'Informar horários disponíveis',
          steps: [
            step({
              agent: 'AgendaAgent',
              action: 'consultar_horarios',
              description: 'Buscar horários livres',
              input: { servico: ent.servico, quando: ent.quando, barbeiro: ent.barbeiro },
              dependsOn: [],
              compensable: false,
            }),
          ],
        };

      case 'agendar': {
        const consultar = step({
          agent: 'AgendaAgent',
          action: 'consultar_horarios',
          description: 'Verificar disponibilidade',
          input: { servico: ent.servico, quando: ent.quando, barbeiro: ent.barbeiro, silent: true },
          dependsOn: [],
          compensable: false,
        });
        const agendar = step({
          agent: 'AgendaAgent',
          action: 'agendar',
          description: 'Criar o agendamento',
          input: { servico: ent.servico, quando: ent.quando, hora: ent.hora, barbeiro: ent.barbeiro },
          dependsOn: [consultar.id],
          compensable: true, // se algo falhar adiante, cancelar
        });
        const cobranca = step({
          agent: 'FinanceAgent',
          action: 'pagar',
          description: 'Gerar cobrança PIX do serviço',
          input: { servico: ent.servico },
          dependsOn: [agendar.id],
          compensable: true,
        });
        const crm = step({
          agent: 'CrmAgent',
          action: 'consultar_cliente',
          description: 'Registrar interação no CRM',
          input: { tipo: 'agendamento' },
          dependsOn: [agendar.id],
          compensable: false,
        });
        return { goal: 'Agendar atendimento', steps: [consultar, agendar, cobranca, crm] };
      }

      case 'remarcar': {
        const consultar = step({
          agent: 'AgendaAgent',
          action: 'consultar_horarios',
          description: 'Buscar novos horários',
          input: { servico: ent.servico, quando: ent.quando, barbeiro: ent.barbeiro, silent: true },
          dependsOn: [],
          compensable: false,
        });
        const remarcar = step({
          agent: 'AgendaAgent',
          action: 'remarcar',
          description: 'Atualizar o agendamento',
          input: { quando: ent.quando, hora: ent.hora },
          dependsOn: [consultar.id],
          compensable: true,
        });
        const crm = step({
          agent: 'CrmAgent',
          action: 'consultar_cliente',
          description: 'Registrar remarcação no CRM',
          input: { tipo: 'remarcacao' },
          dependsOn: [remarcar.id],
          compensable: false,
        });
        return { goal: 'Remarcar atendimento', steps: [consultar, remarcar, crm] };
      }

      case 'cancelar': {
        const cancelar = step({
          agent: 'AgendaAgent',
          action: 'cancelar',
          description: 'Cancelar o agendamento',
          input: {},
          dependsOn: [],
          compensable: false,
        });
        const estorno = step({
          agent: 'FinanceAgent',
          action: 'pagar',
          description: 'Cancelar cobrança pendente, se houver',
          input: { operacao: 'cancelar_cobranca' },
          dependsOn: [cancelar.id],
          compensable: false,
        });
        return { goal: 'Cancelar atendimento', steps: [cancelar, estorno] };
      }

      case 'pagar':
        return {
          goal: 'Resolver pagamento',
          steps: [
            step({
              agent: 'FinanceAgent',
              action: 'pagar',
              description: 'Gerar/explicar cobrança PIX',
              input: { servico: ent.servico },
              dependsOn: [],
              compensable: false,
            }),
          ],
        };

      case 'consultar_cliente':
        return {
          goal: 'Consultar cadastro do cliente',
          steps: [
            step({
              agent: 'CrmAgent',
              action: 'consultar_cliente',
              description: 'Buscar dados e histórico',
              input: { tipo: 'consulta' },
              dependsOn: [],
              compensable: false,
            }),
          ],
        };

      case 'campanha':
        return {
          goal: 'Operar campanha de marketing',
          steps: [
            step({
              agent: 'MarketingAgent',
              action: 'campanha',
              description: 'Criar/segmentar campanha',
              input: { texto: ctx.message.text },
              dependsOn: [],
              compensable: false,
            }),
          ],
        };

      // ===================== Operacionais (painel interno) =====================

      case 'abrir_caixa':
        return this.umPasso('Abrir o caixa', 'CaixaAgent', 'abrir_caixa', {
          operador: ctx.message.customerRef, valor: ent.valor,
        });
      case 'movimentar_caixa':
        return this.umPasso('Movimentar o caixa', 'CaixaAgent', 'movimentar_caixa', {
          mov: ent.mov, valor: ent.valor,
        });
      case 'consultar_caixa':
        return this.umPasso('Consultar o caixa', 'CaixaAgent', 'consultar_caixa', {});
      case 'fechar_caixa':
        return this.umPasso('Fechar o caixa', 'CaixaAgent', 'fechar_caixa', { valor: ent.valor });

      case 'cobrar_inadimplentes':
        return this.umPasso('Cobrar inadimplentes', 'CobrancaAgent', 'cobrar_inadimplentes', {});
      case 'reativar_clientes':
        return this.umPasso('Reativar clientes', 'CobrancaAgent', 'reativar_clientes', {});
      case 'enviar_lembretes':
        return this.umPasso('Enviar lembretes', 'CobrancaAgent', 'enviar_lembretes', {});

      case 'consultar_estoque':
        return this.umPasso('Consultar estoque', 'EstoqueAgent', 'consultar_estoque', {});
      case 'registrar_consumo':
        return this.umPasso('Dar baixa de consumo', 'EstoqueAgent', 'registrar_consumo', {
          produto: ent.produto, qtd: ent.qtd,
        });
      case 'repor_estoque':
        return this.umPasso('Repor estoque', 'EstoqueAgent', 'repor_estoque', {
          produto: ent.produto, qtd: ent.qtd,
        });

      case 'reagendar_em_massa':
        return this.umPasso('Reagendar agenda de um profissional', 'AgendaAgent', 'reagendar_em_massa', {
          barbeiro: ent.barbeiro, quando: ent.quando,
        });

      // ============ Pacotes / Fidelidade / Assinaturas (cliente final) ============

      case 'consultar_pacote':
        return this.umPasso('Consultar pacote', 'MembershipAgent', 'consultar_pacote', {});
      case 'consultar_assinatura':
        return this.umPasso('Consultar assinatura', 'MembershipAgent', 'consultar_assinatura', {});
      case 'consultar_pontos':
        return this.umPasso('Consultar pontos', 'MembershipAgent', 'consultar_pontos', {});
      case 'consultar_nivel':
        return this.umPasso('Consultar nível de fidelidade', 'MembershipAgent', 'consultar_nivel', { tier: ent.tier });
      case 'quanto_economizei':
        return this.umPasso('Consultar economia', 'MembershipAgent', 'quanto_economizei', {});
      case 'usar_pacote':
        return this.umPasso('Usar pacote', 'MembershipAgent', 'usar_pacote', {});
      case 'resgatar_pontos':
        return this.umPasso('Resgatar pontos', 'MembershipAgent', 'resgatar_pontos', { pontos: ent.pontos, confirmado: ent.confirmado });
      case 'cancelar_assinatura':
        return this.umPasso('Cancelar assinatura/pacote', 'MembershipAgent', 'cancelar_assinatura', { alvo: ent.alvo });

      case 'renovar_assinatura': {
        // Saga: renovar (clona snapshot) → registrar no CRM. Sem Payment (receita
        // é reconhecida no uso — fiel ao backend). Se o CRM falhar, compensate()
        // desfaz a renovação.
        const renovar = step({
          agent: 'MembershipAgent', action: 'renovar_assinatura',
          description: 'Renovar assinatura/pacote', input: { alvo: ent.alvo }, dependsOn: [], compensable: true,
        });
        const crm = step({
          agent: 'CrmAgent', action: 'consultar_cliente',
          description: 'Registrar renovação no CRM', input: { tipo: 'renovacao_membership' },
          dependsOn: [renovar.id], compensable: false,
        });
        return { goal: 'Renovar assinatura', steps: [renovar, crm] };
      }

      case 'comprar_pacote': {
        const comprar = step({
          agent: 'MembershipAgent', action: 'comprar_pacote',
          description: 'Vender novo pacote', input: { servico: ent.servico, usos: ent.usos, modo: ent.modo },
          dependsOn: [], compensable: true,
        });
        const crm = step({
          agent: 'CrmAgent', action: 'consultar_cliente',
          description: 'Registrar compra no CRM', input: { tipo: 'compra_pacote' },
          dependsOn: [comprar.id], compensable: false,
        });
        return { goal: 'Comprar pacote', steps: [comprar, crm] };
      }

      default:
        // saudação / dúvida / desconhecido -> sem plano de execução
        return { goal: 'Sem plano automatizável', steps: [] };
    }
  }

  /** Plano de passo único — usado pelas intenções operacionais diretas. */
  private umPasso(
    goal: string, agent: string, action: string, input: Record<string, unknown>,
  ): ExecutionPlan {
    return {
      goal,
      steps: [step({ agent, action, description: goal, input, dependsOn: [], compensable: false })],
    };
  }
}
