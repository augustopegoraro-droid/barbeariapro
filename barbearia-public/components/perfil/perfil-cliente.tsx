"use client";

/* Perfil do cliente final.

   Telefone é SOMENTE LEITURA e chega mascarado da API: sem OTP (D-79) não há
   como provar a posse de um número novo, então trocá-lo pelo site permitiria
   assumir o cadastro de outra pessoa. A saída é falar com a barbearia.

   Foto: no app usa a câmera nativa (`lib/native.ts`); no browser, um
   `<input type="file">` escondido. Os dois caminhos terminam no mesmo
   `PUT /me/profile/foto`, que re-encoda em WebP e apaga o EXIF (D-85). */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type PublicProfile } from "@/lib/api";
import { SolidButton, OutlineButton, SolidLink } from "@/components/ui/buttons";
import { EmptyState } from "@/components/ui/empty-state";
import { Toast, type ToastData } from "@/components/ui/toast";
import { Wordmark } from "@/components/wordmark";
import AtivarNotificacoes from "@/components/ativar-notificacoes";
import { MinhaAssinatura } from "@/components/perfil/minha-assinatura";
import { getCameraPhoto, handleExternalLink, isNativeApp } from "@/lib/native";

/* Mesmo número do fallback verificado de `lib/contato.ts` (a API pública não
   entrega `public_info` no /me, e esta tela não carrega a vitrine inteira só
   para montar um link de WhatsApp). */
const WHATSAPP_DIGITS = "5563984566175";
const WHATSAPP_URL = `https://wa.me/${WHATSAPP_DIGITS}?text=${encodeURIComponent(
  "Olá! Preciso atualizar o telefone do meu cadastro.",
)}`;

const KNOWN_NAME_KEY = "tt_client_name";

const CAMPO =
  "mt-1 w-full rounded-xl border border-borda bg-superficie-2 px-4 py-3 text-tinta placeholder:text-tinta-fraca disabled:opacity-60";

export default function PerfilCliente() {
  const [perfil, setPerfil] = useState<PublicProfile | null>(null);
  const [semSessao, setSemSessao] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [enviandoFoto, setEnviandoFoto] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);
  const inputFoto = useRef<HTMLInputElement>(null);

  const aplicar = useCallback((p: PublicProfile) => {
    setPerfil(p);
    setNome(p.name);
    setEmail(p.email ?? "");
    localStorage.setItem(KNOWN_NAME_KEY, p.name);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        aplicar(await api.profile());
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setSemSessao(true);
        else setErro(e instanceof ApiError ? e.message : "Falha ao carregar.");
      }
    })();
  }, [aplicar]);

  const salvar = useCallback(async () => {
    if (nome.trim().length < 2) {
      setToast({ kind: "erro", message: "Informe seu nome completo." });
      return;
    }
    setSalvando(true);
    try {
      aplicar(
        await api.updateProfile({
          name: nome.trim(),
          // String vazia não é e-mail válido para o backend; só mandamos o
          // campo quando ele tem conteúdo.
          ...(email.trim() ? { email: email.trim() } : {}),
        }),
      );
      setToast({ kind: "sucesso", message: "Dados atualizados." });
    } catch (e) {
      setToast({
        kind: "erro",
        message: e instanceof ApiError ? e.message : "Não foi possível salvar.",
      });
    } finally {
      setSalvando(false);
    }
  }, [nome, email, aplicar]);

  const enviarFoto = useCallback(
    async (file: File) => {
      setEnviandoFoto(true);
      try {
        aplicar(await api.uploadPhoto(file));
        setToast({ kind: "sucesso", message: "Foto atualizada." });
      } catch (e) {
        setToast({
          kind: "erro",
          message:
            e instanceof ApiError ? e.message : "Não foi possível enviar a foto.",
        });
      } finally {
        setEnviandoFoto(false);
      }
    },
    [aplicar],
  );

  const escolherFoto = useCallback(async () => {
    if (isNativeApp()) {
      const file = await getCameraPhoto();
      if (file) await enviarFoto(file);
      return;
    }
    inputFoto.current?.click();
  }, [enviarFoto]);

  const removerFoto = useCallback(async () => {
    setEnviandoFoto(true);
    try {
      aplicar(await api.deletePhoto());
      setToast({ kind: "sucesso", message: "Foto removida." });
    } catch (e) {
      setToast({
        kind: "erro",
        message: e instanceof ApiError ? e.message : "Não foi possível remover.",
      });
    } finally {
      setEnviandoFoto(false);
    }
  }, [aplicar]);

  const sair = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* sessão já inválida — segue para a home mesmo assim */
    }
    localStorage.removeItem(KNOWN_NAME_KEY);
    window.location.href = "/";
  }, []);

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <header className="pt-6 pb-4">
        <Link
          href="/"
          className="inline-flex min-h-11 items-center gap-2 text-sm text-tinta-fraca transition-colors hover:text-tinta-suave"
        >
          <span aria-hidden>←</span>
          <Wordmark fontSize={15} />
        </Link>
        <h1 className="mt-4 font-display text-2xl">Meu perfil</h1>
      </header>

      {semSessao && (
        <div className="mt-6">
          <EmptyState
            message="Você ainda não tem cadastro neste aparelho."
            action={
              <SolidLink size="inline" href="/agendar">
                Agendar horário
              </SolidLink>
            }
          />
        </div>
      )}

      {erro && (
        <p role="alert" className="mt-4 text-vermelho-tinta">
          {erro}
        </p>
      )}

      {!perfil && !semSessao && !erro && (
        <p aria-live="polite" className="mt-6 text-tinta-suave">
          Carregando…
        </p>
      )}

      {perfil && (
        <>
          <section className="flex items-center gap-4" aria-label="Foto">
            <button
              type="button"
              onClick={() => void escolherFoto()}
              disabled={enviandoFoto}
              aria-label="Alterar foto do perfil"
              className="relative h-20 w-20 shrink-0 overflow-hidden rounded-full border border-borda bg-superficie-2 transition-colors hover:border-ouro disabled:opacity-60"
            >
              {perfil.photo_url ? (
                // Foto vem da própria API (WebP quadrado); `next/image` exigiria
                // liberar o host remoto — mesmo padrão de `ui/professional.tsx`.
                <img
                  src={perfil.photo_url}
                  alt="Sua foto de perfil"
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center font-display text-3xl text-tinta-suave">
                  {perfil.name.charAt(0)}
                </span>
              )}
            </button>
            <div className="text-sm">
              <button
                type="button"
                onClick={() => void escolherFoto()}
                disabled={enviandoFoto}
                className="inline-flex min-h-11 items-center font-medium text-ouro underline underline-offset-4 disabled:opacity-60"
              >
                {enviandoFoto ? "Enviando…" : "Alterar foto"}
              </button>
              {perfil.photo_url && (
                <button
                  type="button"
                  onClick={() => void removerFoto()}
                  disabled={enviandoFoto}
                  className="ml-4 inline-flex min-h-11 items-center text-tinta-fraca underline underline-offset-4 disabled:opacity-60"
                >
                  Remover
                </button>
              )}
            </div>
            <input
              ref={inputFoto}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void enviarFoto(file);
              }}
            />
          </section>

          <section className="mt-8" aria-label="Seus dados">
            <label htmlFor="perfil-nome" className="block text-sm text-tinta-suave">
              Nome
            </label>
            <input
              id="perfil-nome"
              value={nome}
              disabled={salvando}
              autoComplete="name"
              onChange={(e) => setNome(e.target.value)}
              className={CAMPO}
            />

            <label
              htmlFor="perfil-email"
              className="mt-4 block text-sm text-tinta-suave"
            >
              E-mail (opcional)
            </label>
            <input
              id="perfil-email"
              type="email"
              value={email}
              disabled={salvando}
              autoComplete="email"
              placeholder="seu@email.com"
              onChange={(e) => setEmail(e.target.value)}
              className={CAMPO}
            />

            <p className="mt-4 block text-sm text-tinta-suave">Telefone</p>
            <p className="mt-1 rounded-xl border border-borda-sutil bg-superficie px-4 py-3 text-tinta tnum">
              {perfil.phone_masked}
            </p>
            <p className="mt-2 text-xs text-tinta-fraca">
              Para alterar seu telefone,{" "}
              <a
                href={WHATSAPP_URL}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => handleExternalLink(e, WHATSAPP_URL)}
                className="text-ouro underline underline-offset-4"
              >
                fale com a gente
              </a>
              .
            </p>

            <div className="mt-6">
              <SolidButton onClick={() => void salvar()} disabled={salvando}>
                {salvando ? "Salvando…" : "Salvar alterações"}
              </SolidButton>
            </div>
          </section>

          <MinhaAssinatura />

          <section className="mt-8" aria-label="Notificações">
            <AtivarNotificacoes />
          </section>

          <section className="mt-8" aria-label="Sessão">
            <OutlineButton className="w-full" onClick={() => void sair()}>
              Sair
            </OutlineButton>
            <p className="mt-3 text-center text-xs text-tinta-fraca">
              Cliente desde{" "}
              {new Date(perfil.member_since).toLocaleDateString("pt-BR", {
                month: "long",
                year: "numeric",
              })}
              .
            </p>
          </section>
        </>
      )}

      {toast && <Toast toast={toast} onClose={() => setToast(null)} />}
    </main>
  );
}
