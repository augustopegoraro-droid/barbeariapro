"use client";

/* CTA de compra de um plano.

   Mesma mecânica de identificação do agendamento (`booking-flow.tsx`): a
   sessão é um cookie HttpOnly que o JS não enxerga, então guardamos só o nome
   em localStorage como memória de UX. Quem já tem sessão vai direto ao
   checkout; quem não tem (ou levou 401) preenche nome/WhatsApp/aceite nos
   MESMOS campos do agendamento (`ui/identificacao.tsx`) antes.

   Nada é confirmado aqui: o backend devolve a URL da Stripe e a assinatura só
   nasce quando o webhook confirmar o pagamento. */

import { useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { SolidButton, Spinner } from "@/components/ui/buttons";
import { IdentificacaoFields } from "@/components/ui/identificacao";

const KNOWN_NAME_KEY = "tt_client_name";

export function CheckoutButton({
  planId,
  planName,
}: {
  planId: number;
  planName: string;
}) {
  const [identificando, setIdentificando] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [acceptPrivacy, setAcceptPrivacy] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  /* Redireciona para a Stripe. `window.location.href` (e não `router.push`):
     o destino é externo. */
  const irParaCheckout = useCallback(async () => {
    const { checkout_url } = await api.checkout(planId);
    window.location.href = checkout_url;
  }, [planId]);

  const assinar = useCallback(async () => {
    setErro(null);
    setEnviando(true);
    try {
      if (!localStorage.getItem(KNOWN_NAME_KEY)) {
        setIdentificando(true);
        return;
      }
      await irParaCheckout();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        localStorage.removeItem(KNOWN_NAME_KEY);
        setIdentificando(true);
        setErro("Confirme seus dados para continuar.");
      } else {
        setErro(
          e instanceof ApiError ? e.message : "Não foi possível iniciar o pagamento.",
        );
      }
    } finally {
      setEnviando(false);
    }
  }, [irParaCheckout]);

  const identificarEAssinar = useCallback(async () => {
    setErro(null);
    const digits = phone.replace(/\D/g, "");
    if (name.trim().length < 2 || digits.length < 10) {
      setErro("Preencha seu nome e um telefone com DDD.");
      return;
    }
    if (!acceptPrivacy) {
      setErro("Aceite a política de privacidade para continuar.");
      return;
    }
    setEnviando(true);
    try {
      const sessao = await api.createSession(name.trim(), digits, acceptPrivacy);
      localStorage.setItem(KNOWN_NAME_KEY, sessao.client_name);
      await irParaCheckout();
    } catch (e) {
      setErro(
        e instanceof ApiError ? e.message : "Não foi possível iniciar o pagamento.",
      );
      setEnviando(false);
    }
  }, [name, phone, acceptPrivacy, irParaCheckout]);

  if (identificando) {
    return (
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void identificarEAssinar();
        }}
      >
        <IdentificacaoFields
          idPrefix={`plano-${planId}`}
          name={name}
          phone={phone}
          acceptPrivacy={acceptPrivacy}
          onNameChange={setName}
          onPhoneChange={setPhone}
          onAcceptPrivacyChange={setAcceptPrivacy}
          phoneHint="Usamos seu número para identificar sua assinatura."
        />
        {erro && (
          <p role="alert" className="text-sm text-vermelho-tinta">
            {erro}
          </p>
        )}
        <SolidButton type="submit" disabled={enviando}>
          {enviando && <Spinner />}
          {enviando ? "Abrindo pagamento…" : "Ir para o pagamento"}
        </SolidButton>
      </form>
    );
  }

  return (
    <div className="space-y-3">
      {erro && (
        <p role="alert" className="text-sm text-vermelho-tinta">
          {erro}
        </p>
      )}
      <SolidButton
        onClick={() => void assinar()}
        disabled={enviando}
        aria-label={`Assinar ${planName}`}
      >
        {enviando && <Spinner />}
        {enviando ? "Abrindo pagamento…" : "Assinar"}
      </SolidButton>
    </div>
  );
}
