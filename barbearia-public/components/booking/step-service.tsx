import type { RefObject } from "react";
import type { PublicService } from "@/lib/api";
import { ServiceCardButton } from "@/components/ui/service-row";

export function StepService({
  services,
  onSelect,
  headingRef,
}: {
  services: PublicService[];
  onSelect: (s: PublicService) => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  return (
    <section aria-label="Escolha o serviço">
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-2xl outline-none"
      >
        O que vai fazer hoje?
      </h1>
      <ul className="mt-4 space-y-2">
        {services.map((s) => (
          <li key={s.id}>
            <ServiceCardButton service={s} onSelect={() => onSelect(s)} />
          </li>
        ))}
      </ul>
    </section>
  );
}
