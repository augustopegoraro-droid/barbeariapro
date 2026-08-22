/* Cliente da API pública (/public/{tenant}/*).

   - Browser: NEXT_PUBLIC_API_URL (inlinada no build) + credentials: 'include'
     (o cookie tt_session cruza apex ↔ api. por ser same-site).
   - Servidor (SSR da home): API_URL_INTERNAL (rede interna do compose). */

const PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE_URL =
  typeof window === "undefined"
    ? process.env.API_URL_INTERNAL ?? PUBLIC_URL
    : PUBLIC_URL;

/* Fallback = "app" (D-79: org 1 tem subdomain='app'; alinhado ao .env.example). */
export const TENANT = process.env.NEXT_PUBLIC_TENANT_SLUG ?? "app";

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
  /* URL absoluta da foto (D-85), servida pela API. null = usar a inicial. */
  photo_url: string | null;
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
  /* ids explícitos (Fase A): destravam o deep-link de remarcação, que antes
     só recebia os NOMES e não conseguia pré-selecionar nada. */
  service_id: number;
  barber_id: number;
  start_at: string;
  end_at: string;
  status: string;
  total_amount: number;
  cancelable: boolean;
  /* Avaliação já enviada (definitiva, sem edição) — null = ainda não avaliou. */
  rating: number | null;
  /* Concluído, sem avaliação e dentro da janela do backend. */
  can_rate: boolean;
};

export type PublicProfile = {
  name: string;
  /* Somente leitura enquanto não houver OTP (D-79): vem MASCARADO da API. */
  phone_masked: string;
  email: string | null;
  photo_url: string | null;
  member_since: string;
};

export type PublicRating = {
  rating: number;
  comment: string | null;
  created_at: string;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return raw<T>(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

/* Sem `Content-Type` fixo: o upload de foto vai como multipart e o boundary
   só é montado corretamente quando o browser escreve o header sozinho. */
async function raw<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${base()}${path}`, {
    credentials: "include",
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

/* Tag do cache da vitrine. O backend invalida sob demanda via
   POST /api/revalidate quando o painel cadastra profissional/serviço/horário
   (D-84) — o `revalidate` abaixo é só o teto de segurança. */
export const INFO_TAG = "public-info";

/* Tag do cache do feed de novidades, invalidada pelo painel a cada
   publicação/edição/arquivamento de post. */
export const FEED_TAG = "public-feed";

export type FeedPost = {
  /* `public_id` (uuid) — o id sequencial não sai do painel. */
  id: string;
  title: string;
  body: string;
  image_url: string | null;
  published_at: string;
  pinned: boolean;
};

/* Feed de novidades. Paginação por CURSOR (`before` = `published_at` do último
   item recebido), não por offset: um post novo entrando no topo entre duas
   páginas não empurra itens para frente. */
export async function fetchFeed(
  opts: { limit?: number; before?: string } = {},
  revalidateSeconds = 300,
): Promise<FeedPost[]> {
  const qs = new URLSearchParams();
  if (opts.limit != null) qs.set("limit", String(opts.limit));
  if (opts.before) qs.set("before", opts.before);
  const suffix = qs.toString() ? `?${qs}` : "";
  const resp = await fetch(`${base()}/feed${suffix}`, {
    next: { revalidate: revalidateSeconds, tags: [FEED_TAG] },
  });
  if (!resp.ok) throw new ApiError(resp.status, "Falha ao carregar novidades.");
  const data: { posts: FeedPost[] } = await resp.json();
  return data.posts;
}

/* Tag do cache dos planos vendáveis online. Invalidada pelo backend quando a
   capacidade de cobrar da barbearia muda (`charges_enabled`, Stripe Connect) —
   é o que faz a página de assinatura sair do "em breve" sem esperar o ISR. */
export const PLANS_TAG = "public-plans";

/* Plano de assinatura/pacote vendável no site. `included_uses` null = uso
   ilimitado dentro da vigência. */
export type MembershipPlanPublic = {
  id: number;
  name: string;
  description: string | null;
  price: number;
  included_uses: number | null;
  duration_days: number;
  services: string[];
};

/* Assinatura vigente do cliente da sessão atual (`GET /me/assinatura`). */
export type ActiveMembership = {
  public_id: string;
  plan_name: string | null;
  status: string;
  start_at: string;
  end_at: string;
  included_uses: number | null;
  used_uses: number;
  services: string[];
};

/* Planos vendáveis. Lista VAZIA é resposta legítima (a barbearia ainda não
   habilitou recebimentos online) — nunca um erro a exibir. */
export async function fetchPlanos(
  revalidateSeconds = 300,
): Promise<MembershipPlanPublic[]> {
  const resp = await fetch(`${base()}/planos`, {
    next: { revalidate: revalidateSeconds, tags: [PLANS_TAG] },
  });
  if (!resp.ok) throw new ApiError(resp.status, "Falha ao carregar os planos.");
  const data: { plans: MembershipPlanPublic[] } = await resp.json();
  return data.plans;
}

export async function fetchInfo(revalidateSeconds = 300): Promise<PublicInfo> {
  // Server-side (home SSR/ISR): usa o cache do Next.
  const resp = await fetch(`${base()}/info`, {
    next: { revalidate: revalidateSeconds, tags: [INFO_TAG] },
  });
  if (!resp.ok) throw new ApiError(resp.status, "Falha ao carregar informações.");
  return resp.json();
}

export const api = {
  info: () => request<PublicInfo>("/info"),
  /* Página seguinte do feed, no browser (botão "Carregar mais"). O SSR da
     primeira página usa `fetchFeed`, que passa pelo cache do Next. */
  feed: (opts: { limit?: number; before?: string } = {}) => {
    const qs = new URLSearchParams();
    if (opts.limit != null) qs.set("limit", String(opts.limit));
    if (opts.before) qs.set("before", opts.before);
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<{ posts: FeedPost[] }>(`/feed${suffix}`);
  },
  slots: (serviceId: number, barberId: number, day: string) =>
    request<{ slots: string[] }>(
      `/slots?service_id=${serviceId}&barber_id=${barberId}&day=${day}`,
    ),
  // `accept_privacy` é o aceite explícito da política (LGPD, D-86) — o backend
  // recusa a sessão sem ele.
  createSession: (name: string, phone: string, acceptPrivacy: boolean) =>
    request<{ client_name: string; is_new_client: boolean }>("/auth/session", {
      method: "POST",
      body: JSON.stringify({ name, phone, accept_privacy: acceptPrivacy }),
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

  /* ─── Perfil do cliente (Fase A) ─────────────────────────────────────── */
  profile: () => request<PublicProfile>("/me/profile"),
  updateProfile: (data: { name?: string; email?: string }) =>
    request<PublicProfile>("/me/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  uploadPhoto: (file: File) => {
    const form = new FormData();
    // Nome do campo = `file`, igual ao parâmetro do endpoint.
    form.append("file", file, file.name || "foto.jpg");
    return raw<PublicProfile>("/me/profile/foto", { method: "PUT", body: form });
  },
  deletePhoto: () =>
    request<PublicProfile>("/me/profile/foto", { method: "DELETE" }),

  /* ─── Avaliação e remarcação ──────────────────────────────────────────── */
  rate: (publicId: string, data: { rating: number; comment?: string }) =>
    request<PublicRating>(`/me/appointments/${publicId}/rating`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  reschedule: (
    publicId: string,
    data: { service_id: number; barber_id: number; start_at: string },
  ) =>
    request<PublicAppointment>(`/me/appointments/${publicId}/reschedule`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /* ─── Assinatura online (Stripe Connect) ──────────────────────────────── */
  planos: () => request<{ plans: MembershipPlanPublic[] }>("/planos"),
  /* Abre o checkout na Stripe. Devolve a URL para onde redirecionar — nada é
     confirmado aqui: quem cria a assinatura é o webhook, depois do pagamento. */
  checkout: (planId: number) =>
    request<{ checkout_url: string; order_public_id: string }>(
      "/memberships/checkout",
      { method: "POST", body: JSON.stringify({ plan_id: planId }) },
    ),
  /* `null` quando a sessão não tem assinatura vigente. */
  minhaAssinatura: () => request<ActiveMembership | null>("/me/assinatura"),

  /* ─── Push nativo (FCM, app Capacitor) ────────────────────────────────── */
  subscribeDevicePush: (token: string, platform: "ios" | "android") =>
    request<void>("/push/device", {
      method: "POST",
      body: JSON.stringify({ token, platform }),
    }),
  unsubscribeDevicePush: (token: string) =>
    request<void>("/push/device", {
      method: "DELETE",
      body: JSON.stringify({ token }),
    }),
  subscribePush: (sub: { endpoint: string; p256dh: string; auth: string; user_agent?: string }) =>
    request<void>("/push/subscription", { method: "POST", body: JSON.stringify(sub) }),
  unsubscribePush: (endpoint: string) =>
    request<void>("/push/subscription", {
      method: "DELETE",
      body: JSON.stringify({ endpoint }),
    }),
};
