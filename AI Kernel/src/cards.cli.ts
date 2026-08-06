/**
 * cards.cli.ts
 * -----------------------------------------------------------------------------
 * Inspeciona os agent cards carregados do vault (knowledge/agents/*.md).
 *
 * Rode com:  npm run cards
 * -----------------------------------------------------------------------------
 */

import * as path from 'path';
import { loadAgentCards } from './kernel/cards';

function main(): void {
  const dir = path.join(__dirname, '..', 'knowledge', 'agents');
  const cards = loadAgentCards(dir);

  console.log(`\nAgent cards carregados de knowledge/agents/ — ${cards.size} card(s)\n`);

  for (const { descriptor: d, body, sourcePath } of cards.values()) {
    const intents = d.capabilities.map((c) => c.intent).join(', ');
    console.log('─'.repeat(72));
    console.log(`${d.name}  v${d.version}  [${d.health}]`);
    console.log(`  arquivo:     ${path.basename(sourcePath)}`);
    console.log(`  descrição:   ${d.description}`);
    console.log(`  intents:     ${intents}`);
    console.log(`  permissões:  ${d.permissions.join(', ')}`);
    console.log(`  ferramentas: ${d.tools.join(', ')}`);
    console.log(`  custo/lat.:  US$ ${d.estimatedCostUsd} · ${d.avgLatencyMs}ms`);
    const preview = body.split('\n').find((l) => l.trim() && !l.startsWith('#'));
    if (preview) console.log(`  corpo:       ${preview.trim().slice(0, 64)}…`);
  }
  console.log('─'.repeat(72));
}

main();
