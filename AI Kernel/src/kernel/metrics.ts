/**
 * kernel/metrics.ts
 * -----------------------------------------------------------------------------
 * Metrics Engine — torna toda decisão mensurável.
 *
 * Assina o Event Bus e acumula métricas globais e por requisição. Esses dados
 * também alimentam o aprendizado contínuo do AI Router (taxa de sucesso por
 * modelo/agente).
 * -----------------------------------------------------------------------------
 */

import { EventBus, KernelEvent } from './eventBus';

interface Agg {
  count: number;
  successos: number;
  falhas: number;
  custoUsd: number;
  latenciaMs: number;
}

function emptyAgg(): Agg {
  return { count: 0, successos: 0, falhas: 0, custoUsd: 0, latenciaMs: 0 };
}

export class MetricsEngine {
  totalRequests = 0;
  totalHandoffs = 0;
  totalCostUsd = 0;
  totalLatencyMs = 0;
  successos = 0;
  falhas = 0;

  porAgente = new Map<string, Agg>();
  porModelo = new Map<string, Agg>();
  porIntent = new Map<string, number>();

  constructor(bus: EventBus) {
    bus.subscribe((e) => this.onEvent(e));
  }

  private bump(map: Map<string, Agg>, key: string, fn: (a: Agg) => void): void {
    const a = map.get(key) ?? emptyAgg();
    fn(a);
    map.set(key, a);
  }

  private onEvent(e: KernelEvent): void {
    switch (e.type) {
      case 'requisicao.iniciada':
        this.totalRequests++;
        break;
      case 'intent.identificada': {
        const name = String(e.payload.intent ?? 'desconhecido');
        this.porIntent.set(name, (this.porIntent.get(name) ?? 0) + 1);
        break;
      }
      case 'step.concluido': {
        const agent = String(e.payload.agent);
        const ok = Boolean(e.payload.ok);
        const cost = Number(e.payload.costUsd ?? 0);
        const lat = Number(e.payload.latencyMs ?? 0);
        const model = e.payload.modelUsed ? String(e.payload.modelUsed) : null;
        this.bump(this.porAgente, agent, (a) => {
          a.count++;
          ok ? a.successos++ : a.falhas++;
          a.custoUsd += cost;
          a.latenciaMs += lat;
        });
        if (model) {
          this.bump(this.porModelo, model, (a) => {
            a.count++;
            ok ? a.successos++ : a.falhas++;
            a.custoUsd += cost;
            a.latenciaMs += lat;
          });
        }
        break;
      }
      case 'handoff.acionado':
        this.totalHandoffs++;
        break;
      case 'resposta.enviada': {
        const ok = Boolean(e.payload.ok);
        ok ? this.successos++ : this.falhas++;
        this.totalCostUsd += Number(e.payload.totalCostUsd ?? 0);
        this.totalLatencyMs += Number(e.payload.totalLatencyMs ?? 0);
        break;
      }
    }
  }

  /** Taxa de sucesso histórica de um agente (usada pelo aprendizado contínuo). */
  taxaSucessoAgente(agent: string): number {
    const a = this.porAgente.get(agent);
    if (!a || a.count === 0) return 1;
    return a.successos / a.count;
  }

  resumo(): string {
    const linhas: string[] = [];
    linhas.push('================ MÉTRICAS GLOBAIS ================');
    linhas.push(`Requisições:        ${this.totalRequests}`);
    linhas.push(`Sucesso / Falha:    ${this.successos} / ${this.falhas}`);
    linhas.push(`Handoffs humanos:   ${this.totalHandoffs}`);
    linhas.push(`Custo total (US$):  ${this.totalCostUsd.toFixed(4)}`);
    linhas.push(`Latência total:     ${this.totalLatencyMs} ms`);
    linhas.push('');
    linhas.push('Uso por intenção:');
    for (const [k, v] of this.porIntent) linhas.push(`  - ${k}: ${v}`);
    linhas.push('');
    linhas.push('Uso por agente (chamadas | sucesso% | custo US$ | latência ms):');
    for (const [k, a] of this.porAgente) {
      const taxa = ((a.successos / a.count) * 100).toFixed(0);
      linhas.push(`  - ${k}: ${a.count} | ${taxa}% | ${a.custoUsd.toFixed(4)} | ${a.latenciaMs}`);
    }
    linhas.push('');
    linhas.push('Uso por modelo (chamadas | custo US$):');
    if (this.porModelo.size === 0) {
      linhas.push('  (sem chamadas a LLM — classificação por regras e agentes determinísticos)');
    } else {
      for (const [k, a] of this.porModelo) {
        linhas.push(`  - ${k}: ${a.count} | ${a.custoUsd.toFixed(4)}`);
      }
    }
    return linhas.join('\n');
  }
}
