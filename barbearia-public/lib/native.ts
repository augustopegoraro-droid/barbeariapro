/* Porta única do bridge Capacitor (Fase B do plano do app nativo).

   O mesmo código roda em três lugares: browser comum (apex), PWA instalado e
   WebView do app (`barbearia-app/`). Só o último tem os plugins nativos, então
   TODO acesso a `@capacitor/*` acontece por `import()` dinâmico dentro da
   função — assim nada disso entra no bundle de quem abre o site pelo Chrome.

   Falha é sempre silenciosa: recurso nativo indisponível degrada para o
   comportamento web (input de arquivo, link normal, sem vibração). */

/* Casa com `appendUserAgent: "TTApp/1"` do `barbearia-app/capacitor.config.ts`.
   Mudar aqui exige mudar lá — é o mesmo contrato. */
export const APP_UA_MARKER = "TTApp/1";

/** Detecção a partir de um User-Agent — serve ao server (`headers()`). */
export function isAppUserAgent(ua: string | null | undefined): boolean {
  return !!ua && ua.includes(APP_UA_MARKER);
}

/** Detecção no cliente. `Capacitor.isNativePlatform()` é a fonte primária;
    o User-Agent cobre o instante antes de o bridge injetar o objeto. */
export function isNativeApp(): boolean {
  if (typeof window === "undefined") return false;
  const cap = (window as unknown as {
    Capacitor?: { isNativePlatform?: () => boolean };
  }).Capacitor;
  if (cap?.isNativePlatform?.()) return true;
  return isAppUserAgent(navigator.userAgent);
}

/** Plataforma nativa corrente, quando houver. */
export function nativePlatform(): "ios" | "android" | null {
  if (typeof window === "undefined") return null;
  const p = (window as unknown as { Capacitor?: { getPlatform?: () => string } })
    .Capacitor?.getPlatform?.();
  return p === "ios" || p === "android" ? p : null;
}

/** Foto pela câmera/galeria nativa. `null` = fora do app ou cancelado. */
export async function getCameraPhoto(): Promise<File | null> {
  if (!isNativeApp()) return null;
  try {
    const { Camera, CameraResultType, CameraSource } = await import(
      "@capacitor/camera"
    );
    const photo = await Camera.getPhoto({
      quality: 80,
      // O backend re-encoda em WebP quadrado 800px e apaga o EXIF (D-85),
      // então não precisamos de edição nem de resolução alta aqui.
      allowEditing: false,
      resultType: CameraResultType.Uri,
      source: CameraSource.Prompt,
      promptLabelHeader: "Foto do perfil",
      promptLabelPhoto: "Escolher da galeria",
      promptLabelPicture: "Tirar foto",
      promptLabelCancel: "Cancelar",
    });
    if (!photo.webPath) return null;
    const blob = await (await fetch(photo.webPath)).blob();
    const ext = photo.format || "jpg";
    return new File([blob], `foto.${ext}`, {
      type: blob.type || `image/${ext}`,
    });
  } catch {
    // Cancelar o seletor levanta — não é erro do ponto de vista da UI.
    return null;
  }
}

/** Abre um link FORA da WebView (senão o usuário fica preso dentro do app). */
export async function openExternalUrl(url: string): Promise<boolean> {
  if (!isNativeApp()) return false;
  // `tel:`/`whatsapp:` não são navegáveis pelo browser in-app do Capacitor —
  // vão para o handler do sistema; http(s) abre no navegador in-app.
  if (!/^https?:/i.test(url)) {
    window.open(url, "_system");
    return true;
  }
  try {
    const { Browser } = await import("@capacitor/browser");
    await Browser.open({ url });
    return true;
  } catch {
    window.open(url, "_system");
    return true;
  }
}

/** Handler de clique para links externos.

    `preventDefault()` tem de ser SÍNCRONO — depois de um `await` o navegador
    já processou o clique e cancelar não adianta mais. Por isso a decisão usa
    `isNativeApp()` (síncrono) e só a abertura em si é assíncrona. */
export function handleExternalLink(
  event: { preventDefault: () => void },
  url: string,
): void {
  if (!isNativeApp()) return;
  event.preventDefault();
  void openExternalUrl(url);
}

/** Vibração curta de confirmação (seleção de estrela, etc.). */
export async function hapticImpact(): Promise<void> {
  if (!isNativeApp()) return;
  try {
    const { Haptics, ImpactStyle } = await import("@capacitor/haptics");
    await Haptics.impact({ style: ImpactStyle.Light });
  } catch {
    /* sem motor háptico — segue sem vibrar */
  }
}

/** Pede permissão e devolve o device token do FCM em `onToken`.
    Canal independente do Web Push (que não existe dentro de WebView). */
export async function registerNativePush(
  onToken: (token: string) => void,
): Promise<"ok" | "denied" | "unsupported"> {
  if (!isNativeApp()) return "unsupported";
  try {
    const { PushNotifications } = await import("@capacitor/push-notifications");
    let status = await PushNotifications.checkPermissions();
    if (status.receive === "prompt" || status.receive === "prompt-with-rationale") {
      status = await PushNotifications.requestPermissions();
    }
    if (status.receive !== "granted") return "denied";
    await PushNotifications.addListener("registration", (t) => onToken(t.value));
    await PushNotifications.register();
    return "ok";
  } catch {
    return "unsupported";
  }
}
