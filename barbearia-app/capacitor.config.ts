import type { CapacitorConfig } from '@capacitor/cli';

/**
 * Casca nativa da Barbearia Taylor & Thedy.
 *
 * Este app NÃO empacota um bundle estático — a WebView aponta para o site público
 * já em produção (`https://taylorethedy.com`, Next.js SSR real, D-79 a D-84). Todo
 * o conteúdo/funcionalidade vive em `barbearia-public/`; mudanças de UI acontecem lá,
 * nunca aqui. `www/` existe só porque o Capacitor exige um `webDir` mesmo com
 * `server.url` remoto — praticamente não é visto pelo usuário.
 */
const config: CapacitorConfig = {
  appId: 'com.taylorethedy.app',
  appName: 'Taylor e Thedy',
  webDir: 'www',
  server: {
    // `/inicio` é a home dedicada ao modo app (ver plano Fase B) — não a landing de
    // marketing usada no browser. Evita a semelhança 1:1 com o site que motiva a
    // rejeição por "wrapper" na App Store Review Guideline 4.2.
    url: 'https://taylorethedy.com/inicio',
    androidScheme: 'https',
    iosScheme: 'https',
    cleartext: false,
    allowNavigation: ['taylorethedy.com', '*.taylorethedy.com'],
    errorPath: 'offline.html',
  },
  // Permite ao backend/frontend distinguir tráfego do app nativo (ex.: esconder
  // header de marketing, CTA de instalação de PWA) inspecionando o User-Agent.
  appendUserAgent: 'TTApp/1',
  ios: {
    contentInset: 'automatic',
  },
  android: {
    allowMixedContent: false,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1500,
      backgroundColor: '#0a0b0d',
      androidSplashResourceName: 'splash',
      androidScaleType: 'CENTER_CROP',
      showSpinner: false,
      splashFullScreen: true,
      splashImmersive: true,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
