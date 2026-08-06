/**
 * tools/notify.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramenta de notificação (WhatsApp/SMS). Simulada — apenas registra o envio.
 * -----------------------------------------------------------------------------
 */

import { Channel } from '../types';

export interface EnvioRegistro {
  canal: Channel;
  para: string;
  texto: string;
  at: number;
}

const enviados: EnvioRegistro[] = [];

export function enviarWhatsApp(para: string, texto: string, canal: Channel = 'whatsapp'): EnvioRegistro {
  const reg: EnvioRegistro = { canal, para, texto, at: Date.now() };
  enviados.push(reg);
  return reg;
}

export function envios(): EnvioRegistro[] {
  return enviados;
}
