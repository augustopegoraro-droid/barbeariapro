/**
 * kernel/util.ts — utilitários comuns.
 */
import { randomUUID } from 'crypto';

export const id = (prefix = ''): string =>
  prefix ? `${prefix}_${randomUUID().slice(0, 8)}` : randomUUID();

export const now = (): number => Date.now();

export const brl = (v: number): string =>
  v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

export function fmtData(ts: number): string {
  return new Date(ts).toLocaleString('pt-BR', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function fmtHora(ts: number): string {
  return new Date(ts).toLocaleString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const sleep = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));
