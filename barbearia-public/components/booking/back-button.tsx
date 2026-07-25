export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="mt-6 inline-flex min-h-11 items-center text-sm text-tinta-fraca underline underline-offset-4 transition-colors hover:text-tinta-suave"
    >
      ← Voltar
    </button>
  );
}
