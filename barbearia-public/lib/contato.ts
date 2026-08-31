/* Contatos da barbearia.

   A API só devolve o que o gestor cadastrou em `/admin/empresa`; hoje
   `public_info` volta **vazio** em produção, e sem estes valores o site fica
   sem WhatsApp, sem telefone e sem Instagram — some o bloco inteiro de
   contato. Estes são os dados verificados (letreiro da fachada real, em
   `assets/images/fachada-real.png`, e confirmação do dono em 2026-07-25).

   Assim que a empresa preencher o cadastro, a API vence o fallback sozinha —
   não é preciso mexer aqui. */

import type { PublicInfo } from "@/lib/api";
import { dateLong, timeHM } from "@/lib/format";

/** Número (com DDI) que recebe a confirmação do agendamento feito pelo site: ao
 * concluir, o cliente é redirecionado para o WhatsApp com a mensagem pronta e só
 * aperta enviar. Fixo de propósito — é o número operacional que a recepção
 * acompanha, independente do que estiver no cadastro da empresa. */
export const WHATSAPP_AGENDAMENTO_DIGITS = "5563984566175";

/** `https://wa.me/<num>?text=...` com serviço, profissional e horário do
 * agendamento pré-preenchidos. */
export function whatsappConfirmUrl(
  appt: { service_name: string; barber_name: string; start_at: string },
  rescheduled = false,
): string {
  const abertura = rescheduled
    ? "Olá! Confirmo meu horário *remarcado* na Taylor & Thedy:"
    : "Olá! Confirmo meu agendamento na Taylor & Thedy:";
  const msg = [
    abertura,
    "",
    `✂️ Serviço: ${appt.service_name}`,
    `💈 Profissional: ${appt.barber_name}`,
    `📅 ${dateLong(appt.start_at)} às ${timeHM(appt.start_at)}`,
  ].join("\n");
  return `https://wa.me/${WHATSAPP_AGENDAMENTO_DIGITS}?text=${encodeURIComponent(msg)}`;
}

const VERIFICADO = {
  whatsapp: "(63) 98456-6175",
  phone: "(63) 3215-2164",
  instagram: "taylorethedy_",
  /* Perfil do Facebook — informado pelo dono em 2026-07-25. A API pública não
     tem campo para redes além do Instagram, então este vive só aqui. */
  facebook: "taylor.thedy",
  address:
    "LO 01 - Q. 103 Sul, Rua SO 11, 60 - Plano Diretor Sul, Palmas - TO, 77015-028",
} as const;

export type Contato = {
  address: string;
  phone: string;
  whatsapp: string;
  /** Sem "@" — os componentes montam a URL e o rótulo. */
  instagram: string;
  facebook: string;
  whatsappDigits: string;
  phoneDigits: string;
  instagramUrl: string;
  facebookUrl: string;
};

const GOOGLE_MAPS_URL = "https://maps.app.goo.gl/8QKLfpgmMgsr5CVMA";

/** Função pura — mora fora de qualquer módulo "use client" para poder ser
 * chamada tanto de Server Components (`app/page.tsx`) quanto de Client
 * Components (`components/ui/endereco.tsx`). */
export function mapsUrl(_endereco: string) {
  return GOOGLE_MAPS_URL;
}

export function resolverContato(info: PublicInfo): Contato {
  const p = info.public_info;
  const whatsapp = p.whatsapp || VERIFICADO.whatsapp;
  const phone = p.phone || VERIFICADO.phone;
  const instagram = (p.instagram || VERIFICADO.instagram).replace("@", "");

  return {
    address: p.address || VERIFICADO.address,
    phone,
    whatsapp,
    instagram,
    facebook: VERIFICADO.facebook,
    whatsappDigits: `55${whatsapp.replace(/\D/g, "")}`,
    phoneDigits: phone.replace(/\D/g, ""),
    instagramUrl: `https://www.instagram.com/${instagram}`,
    facebookUrl: `https://www.facebook.com/${VERIFICADO.facebook}`,
  };
}
