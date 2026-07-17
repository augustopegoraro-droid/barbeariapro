"use client";

/* Incentivo à instalação como PWA — mitigação central do cap de storage do
   iOS Safari (Fase 0 da auditoria): instalado, o site não perde a sessão. */

import { useEffect, useState } from "react";

const DISMISSED_KEY = "tt_install_dismissed";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
};

export default function InstallBanner() {
  const [visible, setVisible] = useState(false);
  const [isIOS, setIsIOS] = useState(false);
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    if (localStorage.getItem(DISMISSED_KEY)) return;
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      // iOS Safari
      (navigator as unknown as { standalone?: boolean }).standalone === true;
    if (standalone) return;

    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    setIsIOS(ios);
    if (ios) {
      setVisible(true);
      return;
    }
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
      setVisible(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (!visible) return null;

  return (
    <aside className="mt-6 rounded-xl border border-aco-claro bg-aco p-4">
      <p className="font-medium">Adicione à tela de início</p>
      <p className="mt-1 text-sm text-prata-suave">
        {isIOS
          ? "Toque em Compartilhar e depois em “Adicionar à Tela de Início” — assim você fica sempre conectado e agenda em 2 toques."
          : "Instale o atalho e agende em 2 toques, sem precisar se identificar de novo."}
      </p>
      <div className="mt-3 flex gap-3">
        {!isIOS && deferred && (
          <button
            className="rounded-lg bg-destaque px-4 py-2 text-sm font-semibold text-grafite"
            onClick={() => void deferred.prompt()}
          >
            Instalar
          </button>
        )}
        <button
          className="rounded-lg px-4 py-2 text-sm text-cinza underline underline-offset-4"
          onClick={() => {
            localStorage.setItem(DISMISSED_KEY, "1");
            setVisible(false);
          }}
        >
          Agora não
        </button>
      </div>
    </aside>
  );
}
