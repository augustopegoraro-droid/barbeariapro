/* Avatar + cartão de profissional (UI_SPEC_V2 §2 item 4): avatar em
   superfície-2 com inicial display em tinta-suave; card branco sombra+fio. */

import type { PublicProfessional } from "@/lib/api";

export function ProfessionalAvatar({
  name,
  size = 10,
}: {
  name: string;
  size?: 9 | 10;
}) {
  return (
    <span
      aria-hidden
      className={`flex ${size === 10 ? "h-10 w-10" : "h-9 w-9"} items-center justify-center rounded-full bg-superficie-2 font-display font-semibold text-tinta-suave`}
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
  avatarSize?: 9 | 10;
}) {
  return (
    <>
      <ProfessionalAvatar name={professional.name} size={avatarSize} />
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
