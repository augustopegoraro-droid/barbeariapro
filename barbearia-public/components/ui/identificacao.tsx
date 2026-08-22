/* Identificação do cliente final (nome + WhatsApp + aceite da política).

   Extraído de `booking/step-confirm.tsx` para ser o ÚNICO lugar onde o
   titular entra na base (LGPD/D-86): agendamento e compra de assinatura usam
   exatamente os mesmos campos, a mesma validação visual e o mesmo aceite. */

import { maskPhone } from "@/lib/format";

const CAMPO =
  "mt-1 w-full rounded-lg border border-borda bg-superficie px-3 py-3 text-tinta transition-colors placeholder:text-tinta-fraca focus:border-borda-ativa";

export function IdentificacaoFields({
  idPrefix = "id",
  name,
  phone,
  acceptPrivacy,
  onNameChange,
  onPhoneChange,
  onAcceptPrivacyChange,
  phoneHint = "Usamos seu número para confirmar e lembrar do horário.",
}: {
  /* Prefixo dos ids/labels — evita colisão quando o formulário convive com
     outro na mesma página. */
  idPrefix?: string;
  name: string;
  phone: string;
  acceptPrivacy: boolean;
  onNameChange: (v: string) => void;
  onPhoneChange: (v: string) => void;
  onAcceptPrivacyChange: (v: boolean) => void;
  phoneHint?: string;
}) {
  const nomeId = `${idPrefix}-nome`;
  const telId = `${idPrefix}-telefone`;

  return (
    <>
      <div>
        <label htmlFor={nomeId} className="block text-sm font-medium text-tinta">
          Seu nome
        </label>
        <input
          id={nomeId}
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          autoComplete="name"
          required
          minLength={2}
          className={CAMPO}
          placeholder="Como podemos te chamar"
        />
      </div>
      <div>
        <label htmlFor={telId} className="block text-sm font-medium text-tinta">
          WhatsApp / celular
        </label>
        <input
          id={telId}
          value={phone}
          onChange={(e) => onPhoneChange(maskPhone(e.target.value))}
          inputMode="tel"
          autoComplete="tel-national"
          required
          className={`${CAMPO} tnum`}
          placeholder="(63) 99999-9999"
        />
        <p className="mt-1 text-xs text-tinta-suave">{phoneHint}</p>
      </div>
      <label className="flex items-start gap-3 py-1 text-sm text-tinta-suave">
        <input
          type="checkbox"
          checked={acceptPrivacy}
          onChange={(e) => onAcceptPrivacyChange(e.target.checked)}
          required
          className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--ouro)]"
        />
        <span>
          Li e aceito a{" "}
          <a
            href="/privacidade"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-4 hover:text-tinta"
          >
            política de privacidade
          </a>
          . Você pode pedir para sair das mensagens quando quiser.
        </span>
      </label>
    </>
  );
}
