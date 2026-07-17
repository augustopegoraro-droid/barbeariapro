/* Cliente da API pública (/public/{tenant}/*).

   - Browser: NEXT_PUBLIC_API_URL (inlinada no build) + credentials: 'include'
     (o cookie tt_session cruza apex ↔ api. por ser same-site).
   - Servidor (SSR da home): API_URL_INTERNAL (rede interna do compose). */

const PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE_URL =
  typeof window === "undefined"
    ? process.env.API_URL_INTERNAL ?? PUBLIC_URL
    : PUBLIC_URL;

export const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG ?? "taylor";

const base = () => `${BASE_URL}/public/${TENANT}`;

export type PublicService = {
  id: number;
  name: string;
  category: string;
  duration_min: number;
  price: number;
  barber_ids: number[];
};

export type PublicProfessional = {
  id: number;
  name: string;
  specialty: string | null;
};

export type PublicHour = {
  weekday: number; // 0=domingo ... 6=sábado
  open_time: string;
  close_time: string;
};

export type PublicInfo = {
  name: string;
  services: PublicService[];
  professionals: PublicProfessional[];
  hours: PublicHour[];
  banner: Record<string, unknown>;
  public_info: {
    address?: string;
    phone?: string;
    whatsapp?: string;
    instagram?: string;
    website?: string;
    logo_url?: string;
  };
};

export type PublicAppointment = {
  public_id: string;
  service_name: string;
  barber_name: string;
  start_at: string;
  end_at: string;
  status: string;
  total_amount: number;
  cancelable: boolean;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${base()}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = "Algo deu errado. Tente novamente.";
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export async function fetchInfo(revalidateSeconds = 300): Promise<PublicInfo> {
  // Server-side (home SSR/ISR): usa o cache do Next.
  const resp = await fetch(`${base()}/info`, {
    next: { revalidate: revalidateSeconds },
  });
  if (!resp.ok) throw new ApiError(resp.status, "Falha ao carregar informações.");
  return resp.json();
}

export const api = {
  info: () => request<PublicInfo>("/info"),
  slots: (serviceId: number, barberId: number, day: string) =>
    request<{ slots: string[] }>(
      `/slots?service_id=${serviceId}&barber_id=${barberId}&day=${day}`,
    ),
  createSession: (name: string, phone: string) =>
    request<{ client_name: string; is_new_client: boolean }>("/auth/session", {
      method: "POST",
      body: JSON.stringify({ name, phone }),
    }),
  book: (serviceId: number, barberId: number, startAt: string) =>
    request<PublicAppointment>("/appointments", {
      method: "POST",
      body: JSON.stringify({
        service_id: serviceId,
        barber_id: barberId,
        start_at: startAt,
      }),
    }),
  myAppointments: () => request<PublicAppointment[]>("/me/appointments"),
  cancel: (publicId: string) =>
    request<PublicAppointment>(`/me/appointments/${publicId}/cancel`, {
      method: "POST",
    }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
};
