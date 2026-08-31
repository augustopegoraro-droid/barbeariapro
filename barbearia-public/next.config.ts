import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Runtime enxuto: build standalone (`node server.js`), menos RSS na VM 4 GB.
  output: "standalone",
  // O site é servido atrás do nginx da VM (apex). Sem rewrites em prod: o browser
  // fala direto com a API pública (NEXT_PUBLIC_API_URL) com credentials: 'include'.
  poweredByHeader: false,
  // Dev na rede local (teste no celular): DEV_API_PROXY=http://localhost:8000 +
  // NEXT_PUBLIC_API_URL="" fazem o browser chamar /public/* same-origin e o Next
  // proxyar ao backend — sem CORS e com cookie funcionando em qualquer IP.
  async rewrites() {
    const target = process.env.DEV_API_PROXY;
    if (!target) return [];
    return [{ source: "/public/:path*", destination: `${target}/public/:path*` }];
  },
};

export default nextConfig;
