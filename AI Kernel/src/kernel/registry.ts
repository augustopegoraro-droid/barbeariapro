/**
 * kernel/registry.ts
 * -----------------------------------------------------------------------------
 * Agent Registry — catálogo de agentes.
 *
 * O Kernel nunca conhece os agentes diretamente; toda descoberta passa por
 * aqui. Cada agente publica nome, descrição, capacidades, permissões,
 * ferramentas, custo, latência, versão e estado de saúde.
 * -----------------------------------------------------------------------------
 */

import { Agent, AgentDescriptor, Health, IntentName } from '../types';

export class AgentRegistry {
  private agents = new Map<string, Agent>();

  register(agent: Agent): void {
    this.agents.set(agent.descriptor.name, agent);
  }

  get(name: string): Agent | undefined {
    return this.agents.get(name);
  }

  descriptors(): AgentDescriptor[] {
    return [...this.agents.values()].map((a) => a.descriptor);
  }

  /** Agentes saudáveis que declaram capacidade para a intenção. */
  capazesPara(intent: IntentName): Agent[] {
    return [...this.agents.values()].filter(
      (a) =>
        a.descriptor.health !== 'down' &&
        a.descriptor.capabilities.some((c) => c.intent === intent),
    );
  }

  setHealth(name: string, health: Health): void {
    const a = this.agents.get(name);
    if (a) a.descriptor.health = health;
  }

  /**
   * Substitui o descriptor publicado por um agente. Usado pelos agent cards
   * (knowledge/agents/*.md) para tornar o markdown a fonte de verdade.
   */
  applyDescriptor(name: string, descriptor: AgentDescriptor): boolean {
    const a = this.agents.get(name);
    if (!a) return false;
    a.descriptor = descriptor;
    return true;
  }
}
