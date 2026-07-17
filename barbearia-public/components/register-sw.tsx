"use client";

import { useEffect } from "react";

/* Registra o service worker (requisito de instalabilidade PWA no Android;
   inofensivo no iOS). O SW em si é mínimo — não fazemos cache offline de
   dados de agenda, só o suficiente para o navegador tratar como app. */
export default function RegisterSW() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* sem SW o site continua funcionando normalmente */
      });
    }
  }, []);
  return null;
}
