"use client";

/* "Modo app": o site está sendo renderizado dentro da WebView do Capacitor.

   O valor é calculado no SERVER (User-Agent em `app/layout.tsx`) e descido por
   contexto — assim o header/CTA de marketing nunca chegam a piscar antes de um
   check no cliente. Fora do app o valor é `false` e nada muda. */

import { createContext, useContext, type ReactNode } from "react";

const AppModeContext = createContext(false);

export function AppModeProvider({
  isApp,
  children,
}: {
  isApp: boolean;
  children: ReactNode;
}) {
  return <AppModeContext value={isApp}>{children}</AppModeContext>;
}

export function useIsApp(): boolean {
  return useContext(AppModeContext);
}
