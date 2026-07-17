import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // O site é servido atrás do nginx da VM (apex). Sem rewrites: o browser fala
  // direto com a API pública (NEXT_PUBLIC_API_URL) com credentials: 'include'.
  poweredByHeader: false,
};

export default nextConfig;
