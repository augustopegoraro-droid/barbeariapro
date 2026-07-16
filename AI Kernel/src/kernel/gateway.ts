/**
 * kernel/gateway.ts
 * -----------------------------------------------------------------------------
 * Gateway — recebe mensagens de qualquer canal e converte para um formato
 * único (InboundMessage) antes de entregar ao Kernel.
 * -----------------------------------------------------------------------------
 */

import { Channel, InboundMessage } from '../types';
import { id, now } from './util';

export interface RawInput {
  channel: Channel;
  from: string; // telefone, handle, etc.
  text: string;
  locale?: string;
}

export class Gateway {
  normalizar(raw: RawInput): InboundMessage {
    return {
      id: id('msg'),
      correlationId: id('req'),
      channel: raw.channel,
      customerRef: raw.from.replace(/\D/g, '') || raw.from,
      text: raw.text.trim(),
      receivedAt: now(),
      locale: raw.locale ?? 'pt-BR',
    };
  }
}
