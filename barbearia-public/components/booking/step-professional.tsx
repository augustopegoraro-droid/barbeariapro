import type { RefObject } from "react";
import type { PublicProfessional, PublicService } from "@/lib/api";
import { ProfessionalCardButton } from "@/components/ui/professional";
import { BackButton } from "@/components/booking/back-button";

export function StepProfessional({
  service,
  professionals,
  onSelect,
  onBack,
  headingRef,
}: {
  service: PublicService;
  professionals: PublicProfessional[];
  onSelect: (p: PublicProfessional) => void;
  onBack: () => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  return (
    <section aria-label="Escolha o profissional">
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-2xl outline-none"
      >
        Quem vai te atender?
      </h1>
      <p className="mt-1 text-sm text-tinta-suave">{service.name}</p>
      <ul className="mt-4 space-y-2">
        {professionals.map((p) => (
          <li key={p.id}>
            <ProfessionalCardButton professional={p} onSelect={() => onSelect(p)} />
          </li>
        ))}
      </ul>
      {professionals.length === 0 && (
        <p className="mt-4 text-tinta-suave">
          Nenhum profissional disponível para este serviço agora.
        </p>
      )}
      <BackButton onClick={onBack} />
    </section>
  );
}
