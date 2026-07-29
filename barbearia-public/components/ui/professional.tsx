/* Avatar + cartão de profissional (UI_SPEC_V2 §2 item 4): avatar em
   superfície-2 com inicial display em tinta-suave; card branco sombra+fio. */

import type { PublicProfessional } from "@/lib/api";

const AVATAR_SIZE = { 9: "h-9 w-9", 10: "h-10 w-10", 16: "h-16 w-16" } as const;

/* Foto do profissional quando o gestor enviou uma (D-85); inicial do nome como
   fallback — a barbearia pode ter só parte da equipe fotografada. O backend já
   entrega WebP quadrado 800px, então `<img>` cru basta (sem next/image, que
   exigiria liberar o host remoto). */
export function ProfessionalAvatar({
  name,
  photoUrl,
  size = 10,
}: {
  name: string;
  photoUrl?: string | null;
  size?: keyof typeof AVATAR_SIZE;
}) {
  const box = AVATAR_SIZE[size];
  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt={`Foto de ${name}`}
        loading="lazy"
        decoding="async"
        className={`${box} shrink-0 rounded-full object-cover`}
      />
    );
  }
  return (
    <span
      aria-hidden
      className={`flex ${box} shrink-0 items-center justify-center rounded-full bg-superficie-2 font-display font-semibold text-tinta-suave`}
    >
      {name.charAt(0)}
    </span>
  );
}

export function ProfessionalIdentity({
  professional,
  avatarSize = 10,
}: {
  professional: PublicProfessional;
  avatarSize?: keyof typeof AVATAR_SIZE;
}) {
  return (
    <>
      <ProfessionalAvatar
        name={professional.name}
        photoUrl={professional.photo_url}
        size={avatarSize}
      />
      <span>
        <span className="block font-medium text-tinta">{professional.name}</span>
        {professional.specialty && (
          <span className="block text-xs text-tinta-fraca">
            {professional.specialty}
          </span>
        )}
      </span>
    </>
  );
}

export function ProfessionalCardButton({
  professional,
  onSelect,
}: {
  professional: PublicProfessional;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="flex w-full items-center gap-3 rounded-xl border border-borda-sutil bg-superficie px-4 py-4 text-left transition-colors hover:bg-superficie-2 active:scale-[0.99]"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <ProfessionalIdentity professional={professional} />
    </button>
  );
}
