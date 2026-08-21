"use client";

/* Registro de push NATIVO (FCM) dentro do app.

   Web Push não existe em WKWebView/WebView, então `components/ativar-
   notificacoes.tsx` (VAPID) só serve ao site. Aqui pedimos a permissão nativa
   e mandamos o device token para `POST /public/{sub}/push/device`.

   Silencioso de propósito: fora do app não renderiza nem chama nada, e uma
   recusa de permissão não vira erro na tela. */

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { isNativeApp, nativePlatform, registerNativePush } from "@/lib/native";

const TOKEN_KEY = "tt_fcm_token";

export default function RegistrarPushNativo() {
  const feito = useRef(false);

  useEffect(() => {
    if (feito.current || !isNativeApp()) return;
    feito.current = true;

    void registerNativePush((token) => {
      const plataforma = nativePlatform();
      if (!plataforma) return;
      // Sem sessão de cliente o backend devolve 401 — nada a fazer, o registro
      // acontece de novo na próxima abertura, já com sessão.
      void api
        .subscribeDevicePush(token, plataforma)
        .then(() => localStorage.setItem(TOKEN_KEY, token))
        .catch(() => undefined);
    });
  }, []);

  return null;
}
