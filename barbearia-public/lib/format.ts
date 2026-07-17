const TZ = "America/Sao_Paulo";

export const money = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const weekdayShort = (d: Date) =>
  d.toLocaleDateString("pt-BR", { weekday: "short", timeZone: TZ }).replace(".", "");

export const dayNumber = (d: Date) =>
  d.toLocaleDateString("pt-BR", { day: "2-digit", timeZone: TZ });

export const monthShort = (d: Date) =>
  d.toLocaleDateString("pt-BR", { month: "short", timeZone: TZ }).replace(".", "");

export const timeHM = (iso: string) =>
  new Date(iso).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TZ,
  });

export const dateLong = (iso: string) =>
  new Date(iso).toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: TZ,
  });

/** Data local (America/Sao_Paulo) no formato YYYY-MM-DD para a query de slots. */
export const localDayISO = (d: Date) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
  return parts; // en-CA já sai YYYY-MM-DD
};

export const WEEKDAYS_PT = [
  "Domingo",
  "Segunda",
  "Terça",
  "Quarta",
  "Quinta",
  "Sexta",
  "Sábado",
];

/** Máscara de telefone BR enquanto digita: (63) 99999-9999 */
export const maskPhone = (raw: string) => {
  const d = raw.replace(/\D/g, "").slice(0, 11);
  if (d.length <= 2) return d;
  if (d.length <= 7) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
};
