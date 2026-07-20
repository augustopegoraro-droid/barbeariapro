"use client";

/* Hero cinematográfico da home (D-79 → D-80): vídeo de drone da barbearia com
   SCROLL-SCRUBBING — ao rolar para baixo, o vídeo "passa" (avança quadro a
   quadro amarrado ao scroll, estilo site premium 2030). Poster de capa antes de
   carregar; mudo; sem áudio.

   Estrutura: um wrapper ALTO (200svh) com uma camada STICKY de 100svh — o vídeo
   e o conteúdo ficam presos na tela enquanto o scroll varre a timeline. Assim o
   CTA "Agendar horário" permanece SEMPRE na zona do polegar durante todo o hero
   (conversão em 1º lugar), e o fluxo de agendamento vem logo abaixo.

   Respeita prefers-reduced-motion (sem scrub: primeiro quadro estático). */

import Link from "next/link";
import { useEffect, useRef } from "react";

export function HeroCinematic({
  name,
  logoUrl,
}: {
  name: string;
  logoUrl?: string;
}) {
  const wrapperRef = useRef<HTMLElement>(null);
  const stickyRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const cueRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const video = videoRef.current;
    const wrapper = wrapperRef.current;
    if (!video || !wrapper) return;

    // Não deixar o vídeo tocar sozinho — quem comanda o tempo é o scroll.
    video.pause();

    // iOS/Safari só permitem "seek" fluido depois que o vídeo é destravado por
    // um gesto e está carregado — destrava no 1º toque/scroll (play→pause mudo).
    let unlocked = reduce; // em reduced-motion não há scrub para destravar
    const unlock = () => {
      if (unlocked) return;
      unlocked = true;
      video.play().then(() => video.pause()).catch(() => {});
    };

    if (reduce) return; // scrub desligado: fica no primeiro quadro (poster)

    let raf = 0;
    let target = 0;
    const duration = () => (Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 14);

    const update = () => {
      raf = 0;
      const scrollable = wrapper.offsetHeight - window.innerHeight;
      if (scrollable <= 0) return;
      const scrolled = Math.min(scrollable, Math.max(0, -wrapper.getBoundingClientRect().top));
      const p = scrolled / scrollable;

      // Avança a timeline do vídeo com o scroll.
      target = p * duration();
      if (video.readyState >= 2 && Math.abs(video.currentTime - target) > 0.02) {
        try {
          video.currentTime = target;
        } catch {
          /* seek antes de metadata: ignora, próximo tick corrige */
        }
      }

      // Escurece um toque no fim + esconde a seta de rolagem; a marca faz um
      // leve parallax para cima. O CTA permanece 100% visível (conversão).
      if (overlayRef.current) overlayRef.current.style.opacity = `${0.4 + p * 0.35}`;
      if (cueRef.current) cueRef.current.style.opacity = `${Math.max(0, 1 - p * 4)}`;
      if (contentRef.current) contentRef.current.style.transform = `translate3d(0, ${p * -28}px, 0)`;
    };

    const onScroll = () => {
      unlock();
      if (!raf) raf = requestAnimationFrame(update);
    };

    // Garante que o seek funcione assim que houver quadros disponíveis.
    const onLoaded = () => onScroll();
    video.addEventListener("loadeddata", onLoaded);
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    window.addEventListener("touchstart", unlock, { passive: true });
    return () => {
      if (raf) cancelAnimationFrame(raf);
      video.removeEventListener("loadeddata", onLoaded);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("touchstart", unlock);
    };
  }, []);

  return (
    // Wrapper alto: o excedente de altura é o "trilho" do scrub.
    <section ref={wrapperRef} className="relative w-full h-[200svh]" aria-label={`${name} — vídeo da barbearia`}>
      {/* Camada presa na tela durante o hero */}
      <div ref={stickyRef} className="sticky top-0 flex h-[100svh] flex-col overflow-hidden">
        {/* Vídeo de fundo — o tempo é comandado pelo scroll (sem autoplay/loop) */}
        <video
          ref={videoRef}
          className="absolute inset-0 -z-10 h-full w-full object-cover"
          poster="/hero-poster.jpg"
          muted
          playsInline
          preload="auto"
          aria-hidden
        >
          <source src="/hero-drone.mp4" type="video/mp4" />
        </video>

        {/* Véu grafite: legibilidade + escurecimento no fim do scrub. */}
        <div
          ref={overlayRef}
          className="pointer-events-none absolute inset-0 -z-10 will-change-[opacity]"
          style={{
            opacity: 0.4,
            background:
              "linear-gradient(to top, var(--grafite) 0%, color-mix(in srgb, var(--grafite) 55%, transparent) 42%, color-mix(in srgb, var(--grafite) 18%, transparent) 78%, color-mix(in srgb, var(--grafite) 45%, transparent) 100%)",
          }}
          aria-hidden
        />

        {/* Conteúdo: marca no alto, CTA na faixa do polegar (pé) */}
        <div
          ref={contentRef}
          className="relative flex flex-1 flex-col items-center justify-between px-6 pb-[calc(env(safe-area-inset-bottom)+2rem)] pt-16 text-center will-change-transform"
        >
          <div className="flex flex-col items-center">
            {/* Lockup fiel à fachada (cromado sobre a placa, recortado do print
                oficial e corrigido de perspectiva — D-80). `logo_url` do org tem
                precedência quando um arquivo oficial for cadastrado. */}
            <h1 className="flex justify-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={logoUrl || "/logo-lockup.webp"}
                alt={`${name} — Renove seu Estilo`}
                width={1000}
                height={472}
                className="h-auto w-[min(84vw,340px)] drop-shadow-[0_6px_20px_rgba(0,0,0,0.6)]"
              />
            </h1>
            <p className="mt-4 text-sm uppercase tracking-[0.28em] text-prata/90 [text-shadow:0_1px_8px_rgba(0,0,0,0.6)]">
              Barbearia · Palmas/TO
            </p>
          </div>

          {/* Bloco de ação — primeiro alvo do polegar no mobile */}
          <div className="w-full max-w-md">
            <Link
              href="/agendar"
              className="cta-agendar group flex w-full items-center justify-center gap-2 rounded-full px-6 py-4 text-lg font-bold tracking-wide"
            >
              <span className="relative z-10">Agendar horário</span>
              <svg
                className="relative z-10 h-5 w-5 transition-transform duration-200 group-hover:translate-x-1"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2.4}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
            <p className="mt-3 text-sm text-prata [text-shadow:0_1px_6px_rgba(0,0,0,0.7)]">
              <Link
                href="/meus-agendamentos"
                className="underline underline-offset-4"
              >
                Ver meus agendamentos
              </Link>
            </p>
          </div>
        </div>

        {/* Sugestão de rolagem (some ao rolar) */}
        <div
          ref={cueRef}
          className="pointer-events-none absolute inset-x-0 bottom-2 flex flex-col items-center gap-1 text-prata/60 will-change-[opacity]"
          aria-hidden
        >
          <span className="text-[10px] uppercase tracking-[0.25em]">Role para ver</span>
          <span className="h-5 w-[2px] animate-pulse rounded-full bg-prata/50" />
        </div>
      </div>
    </section>
  );
}
