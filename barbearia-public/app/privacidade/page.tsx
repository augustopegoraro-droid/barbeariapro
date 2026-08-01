/* Política de privacidade do site público (LGPD, D-86).

   ⚠️ A versão publicada aqui precisa andar junto com `PRIVACY_POLICY_VERSION`
   em `app/core/privacy.py`: é essa string que fica gravada em
   `consent_records.policy_version` a cada aceite. Mudou o texto → sobe a
   versão no MESMO commit, senão o histórico aponta para um texto que não
   existe mais.

   O conteúdo descreve o tratamento que o sistema realmente faz (verificado no
   código, não presumido). Revisão jurídica ainda pendente — ver DECISIONS D-86. */

import Link from "next/link";

export const metadata = {
  title: "Política de privacidade",
  description:
    "Como a Taylor & Thedy trata seus dados pessoais: o que coletamos, para quê, com quem compartilhamos e como exercer seus direitos.",
};

/* Mesma string de `app/core/privacy.py::PRIVACY_POLICY_VERSION`. */
const VERSAO = "2026-08-01";
const PUBLICADA_EM = "1º de agosto de 2026";

function Secao({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="font-display text-xl text-tinta">{titulo}</h2>
      <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-tinta-suave">
        {children}
      </div>
    </section>
  );
}

export default function PrivacidadePage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-12 pb-32">
      <p className="text-xs uppercase tracking-[0.18em] text-tinta-fraca">
        Versão {VERSAO} · publicada em {PUBLICADA_EM}
      </p>
      <h1 className="mt-3 font-display text-3xl text-tinta">
        Política de privacidade
      </h1>
      <p className="mt-4 text-[15px] leading-relaxed text-tinta-suave">
        Esta política explica como a Barbearia Taylor &amp; Thedy trata os dados
        pessoais de quem agenda pelo site, conversa pelo WhatsApp ou é atendido
        na loja. Ela segue a Lei Geral de Proteção de Dados (Lei 13.709/2018).
      </p>

      <Secao titulo="Quem é responsável">
        <p>
          A Barbearia Taylor &amp; Thedy, em Palmas (TO), é a{" "}
          <strong className="text-tinta">controladora</strong> dos seus dados —
          é ela quem decide o que é coletado e para quê. O sistema de gestão que
          armazena e processa esses dados é fornecido por um{" "}
          <strong className="text-tinta">operador</strong>, que só age conforme
          as instruções da barbearia.
        </p>
      </Secao>

      <Secao titulo="Que dados coletamos">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong className="text-tinta">Identificação:</strong> nome e
            telefone (obrigatórios para agendar). E-mail e data de nascimento,
            quando você informa.
          </li>
          <li>
            <strong className="text-tinta">Atendimento:</strong> serviços
            realizados, profissional, data, valor pago, pacotes e assinaturas,
            pontos de fidelidade.
          </li>
          <li>
            <strong className="text-tinta">Conversas:</strong> o histórico das
            mensagens trocadas com a barbearia pelo WhatsApp, incluindo áudios e
            imagens que você enviar.
          </li>
          <li>
            <strong className="text-tinta">Acesso ao site:</strong> endereço IP
            e informações do navegador/dispositivo, guardados junto da sessão
            que mantém você conectado.
          </li>
        </ul>
        <p>
          Não coletamos dados sensíveis (saúde, biometria, origem racial,
          convicção religiosa). Atualmente este site não utiliza cookies de
          publicidade nem ferramentas de rastreamento de terceiros: o único
          cookie é o que mantém sua sessão aberta para você ver seus
          agendamentos. Caso isso mude, atualizaremos esta política e pediremos
          seu consentimento quando a lei exigir.
        </p>
      </Secao>

      <Secao titulo="Para que usamos">
        <ul className="list-disc space-y-2 pl-5">
          <li>Marcar, confirmar, lembrar e cancelar seus horários.</li>
          <li>Registrar o atendimento, o pagamento e a fidelidade.</li>
          <li>
            Enviar mensagens sobre seu horário e, se você autorizou, avisos e
            convites para voltar.
          </li>
          <li>Cumprir obrigações fiscais e contábeis.</li>
        </ul>
        <p>
          As bases legais são a <em>execução do contrato</em> (o atendimento que
          você pediu), o <em>consentimento</em> (mensagens promocionais, que você
          pode revogar a qualquer momento) e a{" "}
          <em>obrigação legal</em> (guarda fiscal).
        </p>
      </Secao>

      <Secao titulo="Com quem compartilhamos">
        <p>
          Não vendemos seus dados. Eles são acessados por prestadores que
          sustentam o serviço, cada um só com o necessário:
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li>Provedor de infraestrutura em nuvem, onde o sistema roda.</li>
          <li>
            Plataformas de mensagem (WhatsApp/Meta), para as mensagens que você
            troca com a barbearia.
          </li>
          <li>
            Google Agenda, quando o profissional sincroniza a agenda dele.
          </li>
          <li>
            Provedor de inteligência artificial, para o assistente de
            atendimento. As consultas internas do sistema são enviadas sem o seu
            nome.
          </li>
          <li>Processador de pagamentos, para a assinatura do sistema.</li>
        </ul>
        <p>
          Alguns desses serviços ficam fora do Brasil, o que implica
          transferência internacional de dados com as salvaguardas contratuais
          desses fornecedores.
        </p>
      </Secao>

      <Secao titulo="Por quanto tempo guardamos">
        <p>
          Mantemos seus dados enquanto durar seu relacionamento com a barbearia
          e, depois disso, pelo período necessário ao cumprimento de obrigações
          legais e regulatórias (em geral 5 anos para registros fiscais), ao
          exercício regular de direitos em processos administrativos ou
          judiciais e às demais hipóteses previstas na LGPD.
        </p>
        <p>
          Registros de acesso e sessões são apagados por rotina automática
          quando expiram. Se você pedir a eliminação, seus dados de
          identificação são anonimizados e apenas os valores financeiros
          agregados — sem ligação com você — permanecem para a contabilidade.
        </p>
        <p>
          Cópias de segurança (backups) são mantidas por tempo limitado e
          sobrescritas periodicamente, de modo que a exclusão pode levar até o
          próximo ciclo de rotação para alcançá-las.
        </p>
      </Secao>

      <Secao titulo="Seus direitos">
        <p>Você pode, a qualquer momento e sem custo:</p>
        <ul className="list-disc space-y-2 pl-5">
          <li>confirmar se tratamos seus dados e obter uma cópia deles;</li>
          <li>corrigir dados incompletos ou desatualizados;</li>
          <li>pedir a anonimização ou eliminação;</li>
          <li>revogar o consentimento para receber mensagens;</li>
          <li>saber com quem compartilhamos seus dados.</li>
        </ul>
        <p>
          Para parar de receber mensagens automáticas, basta responder{" "}
          <strong className="text-tinta">SAIR</strong> no WhatsApp — seu cadastro
          é atualizado imediatamente. Para os demais direitos, fale com a
          barbearia pelo WhatsApp ou pessoalmente: pedidos de confirmação e de
          acesso aos dados são respondidos em até 15 dias, e os demais em prazo
          razoável, conforme a LGPD.
        </p>
      </Secao>

      <Secao titulo="Segurança">
        <p>
          Adotamos medidas técnicas e organizacionais destinadas a proteger seus
          dados: isolamento lógico dos dados de cada barbearia, acesso da equipe
          limitado por perfil (a recepção não vê o financeiro, por exemplo) e
          registro das ações sensíveis em trilha de auditoria protegida contra
          alteração não autorizada.
        </p>
      </Secao>

      <Secao titulo="Mudanças nesta política">
        <p>
          Quando o texto mudar, publicamos aqui com uma nova versão e data. O
          aceite que você deu fica registrado com a versão que estava no ar
          naquele momento.
        </p>
      </Secao>

      <div className="mt-12 border-t border-borda-sutil pt-6">
        <Link href="/" className="text-ouro underline underline-offset-4">
          Voltar ao início
        </Link>
      </div>
    </main>
  );
}
