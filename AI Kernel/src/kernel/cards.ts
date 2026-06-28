/**
 * kernel/cards.ts
 * -----------------------------------------------------------------------------
 * Agent Cards — descriptors dos agentes publicados como markdown no vault
 * (knowledge/agents/*.md), legíveis por humano (Obsidian) e pelo Kernel.
 *
 * O card é a FONTE DE VERDADE do descriptor: vence o que está hardcoded no
 * código, que passa a ser fallback + alvo de detecção de drift.
 *
 * Parser de frontmatter próprio (subset de YAML) para não introduzir dependência
 * externa em runtime — coerente com o princípio "100% offline" do Kernel.
 *
 * YAML suportado:
 *   key: escalar                  -> string | number | boolean
 *   key: [a, b, c]                -> string[]  (array inline)
 *   key:                          -> objeto (mapa aninhado, indentação 2 espaços)
 *     subchave: valor
 * -----------------------------------------------------------------------------
 */

import * as fs from 'fs';
import * as path from 'path';
import { AgentDescriptor, Capability, Health, IntentName } from '../types';
import { AgentRegistry } from './registry';

export interface AgentCard {
  descriptor: AgentDescriptor;
  body: string; // markdown após o frontmatter (responsabilidades, fluxos, links)
  sourcePath: string;
}

// ---------------------------------------------------------------------------
// Parser de frontmatter (subset de YAML, zero deps)
// ---------------------------------------------------------------------------

function unquote(s: string): string {
  if (
    (s.startsWith('"') && s.endsWith('"')) ||
    (s.startsWith("'") && s.endsWith("'"))
  ) {
    return s.slice(1, -1);
  }
  return s;
}

function parseScalar(v: string): unknown {
  const t = v.trim();
  if (t === '') return '';
  if (t.startsWith('[') && t.endsWith(']')) {
    const inner = t.slice(1, -1).trim();
    if (inner === '') return [];
    return inner.split(',').map((s) => unquote(s.trim()));
  }
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  if (t === 'true') return true;
  if (t === 'false') return false;
  return unquote(t);
}

export function parseFrontmatter(raw: string): {
  data: Record<string, unknown>;
  body: string;
} {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) return { data: {}, body: raw };

  const fm = m[1];
  const body = m[2] ?? '';
  const data: Record<string, unknown> = {};
  const lines = fm.split(/\r?\n/);

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '' || line.trimStart().startsWith('#')) {
      i++;
      continue;
    }
    const colon = line.indexOf(':');
    if (colon === -1) {
      i++;
      continue;
    }
    const key = line.slice(0, colon).trim();
    const rest = line.slice(colon + 1).trim();

    if (rest === '') {
      // Mapa aninhado: consome linhas indentadas seguintes.
      const obj: Record<string, unknown> = {};
      i++;
      while (i < lines.length) {
        const sub = lines[i];
        if (sub.trim() === '') {
          i++;
          continue;
        }
        const subIndent = sub.length - sub.trimStart().length;
        if (subIndent === 0) break; // voltou ao nível raiz
        const sc = sub.indexOf(':');
        if (sc === -1) {
          i++;
          continue;
        }
        obj[sub.slice(0, sc).trim()] = parseScalar(sub.slice(sc + 1));
        i++;
      }
      data[key] = obj;
    } else {
      data[key] = parseScalar(rest);
      i++;
    }
  }

  return { data, body };
}

// ---------------------------------------------------------------------------
// Card -> AgentDescriptor
// ---------------------------------------------------------------------------

function descriptorFromCard(
  data: Record<string, unknown>,
  sourcePath: string,
): AgentDescriptor {
  const obrigatorios = [
    'name',
    'description',
    'version',
    'health',
    'permissions',
    'tools',
    'capabilities',
  ];
  for (const k of obrigatorios) {
    if (!(k in data)) {
      throw new Error(`Card ${sourcePath}: campo obrigatório ausente: '${k}'`);
    }
  }

  const capsRaw = data.capabilities as Record<string, string>;
  const capabilities: Capability[] = Object.entries(capsRaw).map(
    ([intent, description]) => ({
      intent: intent as IntentName,
      description: String(description),
    }),
  );

  return {
    name: String(data.name),
    description: String(data.description),
    capabilities,
    permissions: data.permissions as string[],
    tools: data.tools as string[],
    estimatedCostUsd: Number(data.estimatedCostUsd ?? 0),
    avgLatencyMs: Number(data.avgLatencyMs ?? 0),
    version: String(data.version),
    health: data.health as Health,
  };
}

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------

/** Lê todos os agent cards de um diretório, indexados por descriptor.name. */
export function loadAgentCards(dir: string): Map<string, AgentCard> {
  const cards = new Map<string, AgentCard>();
  if (!fs.existsSync(dir)) return cards;

  for (const file of fs.readdirSync(dir).sort()) {
    if (!file.endsWith('.md')) continue;
    const full = path.join(dir, file);
    const { data, body } = parseFrontmatter(fs.readFileSync(full, 'utf8'));
    if (!data.name) continue; // nota sem frontmatter de agente (ex.: README/MOC)
    const descriptor = descriptorFromCard(data, file);
    cards.set(descriptor.name, { descriptor, body: body.trim(), sourcePath: full });
  }
  return cards;
}

// ---------------------------------------------------------------------------
// Aplicação no Registry (com detecção de drift código x card)
// ---------------------------------------------------------------------------

/** Campos em que código e card divergem (card vence). */
export function descriptorDrift(
  code: AgentDescriptor,
  card: AgentDescriptor,
): string[] {
  const diffs: string[] = [];
  const push = (cond: boolean, campo: string) => {
    if (cond) diffs.push(campo);
  };
  push(code.description !== card.description, 'description');
  push(code.version !== card.version, 'version');
  push(code.health !== card.health, 'health');
  push(code.estimatedCostUsd !== card.estimatedCostUsd, 'estimatedCostUsd');
  push(code.avgLatencyMs !== card.avgLatencyMs, 'avgLatencyMs');
  push(code.permissions.join(',') !== card.permissions.join(','), 'permissions');
  push(code.tools.join(',') !== card.tools.join(','), 'tools');
  const capKey = (c: Capability[]) =>
    c.map((x) => x.intent).sort().join(',');
  push(capKey(code.capabilities) !== capKey(card.capabilities), 'capabilities');
  return diffs;
}

export interface ApplyResult {
  applied: string[]; // agentes cujo descriptor veio do card
  missingCards: string[]; // agentes registrados sem card (mantêm o do código)
  orphanCards: string[]; // cards sem agente registrado
  drift: string[]; // "AgenteX: campo1, campo2"
}

/**
 * Substitui, no registry, o descriptor de cada agente pelo do card homônimo.
 * Avisa sobre drift (código x card), agentes sem card e cards órfãos.
 */
export function applyCardsToRegistry(
  registry: AgentRegistry,
  cards: Map<string, AgentCard>,
  warn: (m: string) => void = (m) => console.warn(m),
): ApplyResult {
  const before = new Map(
    registry.descriptors().map((d) => [d.name, d] as const),
  );
  const result: ApplyResult = {
    applied: [],
    missingCards: [],
    orphanCards: [],
    drift: [],
  };

  for (const [name, code] of before) {
    const card = cards.get(name);
    if (!card) {
      result.missingCards.push(name);
      warn(`[cards] sem card para ${name} — mantendo descriptor do código`);
      continue;
    }
    const d = descriptorDrift(code, card.descriptor);
    if (d.length) {
      result.drift.push(`${name}: ${d.join(', ')}`);
      warn(`[cards] ${name}: card diverge do código (${d.join(', ')}) — card vence`);
    }
    registry.applyDescriptor(name, card.descriptor);
    result.applied.push(name);
  }

  for (const name of cards.keys()) {
    if (!before.has(name)) {
      result.orphanCards.push(name);
      warn(`[cards] card "${name}" não tem agente registrado`);
    }
  }

  return result;
}
