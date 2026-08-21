import PerfilCliente from "@/components/perfil/perfil-cliente";

export const metadata = {
  title: "Meu perfil",
  robots: { index: false, follow: false },
};

export default function PerfilPage() {
  return <PerfilCliente />;
}
