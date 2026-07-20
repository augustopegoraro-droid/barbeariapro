import { fetchInfo, type PublicInfo } from "@/lib/api";
import { money, WEEKDAYS_PT } from "@/lib/format";
import { HeroCinematic } from "@/components/hero-cinematic";

export const revalidate = 300;

function jsonLd(info: PublicInfo, siteUrl: string) {
  return {
    "@context": "https://schema.org",
    "@type": "LocalBusiness",
    name: info.name,
    url: siteUrl,
    address: info.public_info.address || undefined,
    telephone: info.public_info.phone || undefined,
    openingHoursSpecification: info.hours.map((h) => ({
      "@type": "OpeningHoursSpecification",
      dayOfWeek: WEEKDAYS_PT[h.weekday],
      opens: h.open_time,
      closes: h.close_time,
    })),
  };
}

function groupedHours(info: PublicInfo) {
  const byDay = new Map<number, string[]>();
  for (const h of info.hours) {
    const list = byDay.get(h.weekday) ?? [];
    list.push(`${h.open_time}–${h.close_time}`);
    byDay.set(h.weekday, list);
  }
  return byDay;
}

export default async function HomePage() {
  let info: PublicInfo | null = null;
  try {
    info = await fetchInfo(revalidate);
  } catch {
    info = null;
  }

  if (!info) {
    return (
      <main className="mx-auto flex min-h-[80dvh] w-full max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="font-display text-3xl font-semibold">Taylor &amp; Thedy</h1>
        <p className="text-prata-suave">
          Não foi possível carregar as informações agora. Tente novamente em
          instantes.
        </p>
      </main>
    );
  }

  const hours = groupedHours(info);
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://taylorethedy.com";
  const wa = info.public_info.whatsapp?.replace(/\D/g, "");

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd(info, siteUrl)) }}
      />

      {/* Hero cinematográfico: vídeo de drone em tela cheia + lockup + CTA. */}
      <HeroCinematic name={info.name} logoUrl={info.public_info.logo_url} />

      <main className="mx-auto w-full max-w-md px-6 pb-16">
      {/* Serviços */}
      <section aria-labelledby="servicos" className="pt-12">
        <div className="stripe mb-6" aria-hidden />
        <h2 id="servicos" className="font-display text-2xl font-semibold">
          Serviços
        </h2>
        <ul className="mt-4 divide-y divide-aco-claro">
          {info.services.map((s) => (
            <li key={s.id} className="flex items-baseline justify-between gap-4 py-3">
              <div>
                <p className="font-medium">{s.name}</p>
                <p className="text-sm text-cinza">{s.duration_min} min</p>
              </div>
              <p className="font-display text-lg text-destaque tnum">{money(s.price)}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* Profissionais */}
      {info.professionals.length > 0 && (
        <section aria-labelledby="equipe" className="mt-10">
          <h2 id="equipe" className="font-display text-2xl font-semibold">
            Quem atende
          </h2>
          <ul className="mt-4 flex flex-wrap gap-3">
            {info.professionals.map((p) => (
              <li
                key={p.id}
                className="flex items-center gap-3 rounded-xl bg-aco px-4 py-3"
              >
                <span
                  aria-hidden
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-aco-claro font-display font-semibold text-destaque"
                >
                  {p.name.charAt(0)}
                </span>
                <span>
                  <span className="block font-medium">{p.name}</span>
                  {p.specialty && (
                    <span className="block text-xs text-cinza">{p.specialty}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Horários */}
      {hours.size > 0 && (
        <section aria-labelledby="horarios" className="mt-10">
          <h2 id="horarios" className="font-display text-2xl font-semibold">
            Horário de funcionamento
          </h2>
          <ul className="mt-4 space-y-1 text-sm">
            {WEEKDAYS_PT.map((label, weekday) => (
              <li key={weekday} className="flex justify-between py-1">
                <span className={hours.has(weekday) ? "" : "text-cinza"}>{label}</span>
                <span className="tnum text-prata-suave">
                  {hours.get(weekday)?.join(" · ") ?? "Fechado"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Contato */}
      <footer className="mt-10">
        <div className="stripe mb-6" aria-hidden />
        {info.public_info.address && (
          <p className="text-sm text-prata-suave">{info.public_info.address}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-3 text-sm">
          {wa && (
            <a
              className="rounded-lg bg-aco px-4 py-2 font-medium text-verde"
              href={`https://wa.me/${wa}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              WhatsApp
            </a>
          )}
          {info.public_info.instagram && (
            <a
              className="rounded-lg bg-aco px-4 py-2 font-medium"
              href={`https://instagram.com/${info.public_info.instagram.replace("@", "")}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Instagram
            </a>
          )}
          {info.public_info.phone && (
            <a
              className="rounded-lg bg-aco px-4 py-2 font-medium"
              href={`tel:${info.public_info.phone.replace(/\D/g, "")}`}
            >
              Ligar
            </a>
          )}
        </div>
      </footer>
      </main>
    </>
  );
}
