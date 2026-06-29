/**
 * kernel/discovery.ts
 * -----------------------------------------------------------------------------
 * Capability Discovery — recebe uma intenção e identifica quais agentes podem
 * resolvê-la, escolhendo o melhor candidato.
 *
 * O critério combina custo, latência, saúde e taxa de sucesso histórica
 * (esta última vinda do Metrics Engine — aprendizado contínuo).
 * -----------------------------------------------------------------------------
 */

import { Agent, IntentName } from '../types';
import { MetricsEngine } from './metrics';
import { AgentRegistry } from './registry';

export class CapabilityDiscovery {
  constructor(
    private registry: AgentRegistry,
    private metrics: MetricsEngine,
  ) {}

  descobrir(intent: IntentName): Agent[] {
    return this.registry.capazesPara(intent);
  }

  /** Melhor agente para uma intenção, ou undefined se ninguém puder. */
  melhorPara(intent: IntentName): Agent | undefined {
    const candidatos = this.descobrir(intent);
    if (candidatos.length === 0) return undefined;
    if (candidatos.length === 1) return candidatos[0];

    return candidatos
      .map((a) => ({ a, score: this.score(a) }))
      .sort((x, y) => y.score - x.score)[0].a;
  }

  private score(a: Agent): number {
    const d = a.descriptor;
    const saude = d.health === 'healthy' ? 1 : 0.5;
    const sucesso = this.metrics.taxaSucessoAgente(d.name); // 0..1
    const custo = 1 / (1 + d.estimatedCostUsd * 100);
    const latencia = 1 / (1 + d.avgLatencyMs / 1000);
    return saude * 2 + sucesso * 2 + custo + latencia;
  }
}
