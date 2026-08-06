/**
 * ai/llm.ts
 * -----------------------------------------------------------------------------
 * Provedores de modelo de linguagem.
 *
 * O AIRouter (kernel/router.ts) escolhe QUAL modelo usar; aqui ficam os
 * adaptadores que efetivamente chamam cada modelo.
 *
 * MockLLM é determinístico e offline — usado na demo e em testes.
 * RealLLM mostra onde plugar Claude e Gemini de verdade (não executado aqui).
 * -----------------------------------------------------------------------------
 */

export interface LLMRequest {
  model: string;
  prompt: string;
}

export interface LLMResponse {
  text: string;
  model: string;
}

export interface LLMProvider {
  name: string;
  complete(req: LLMRequest): Promise<LLMResponse>;
}

/**
 * Mock determinístico. Não chama rede. Gera respostas plausíveis a partir de
 * marcadores no prompt, de forma que a demo seja estável e reproduzível.
 */
export class MockLLM implements LLMProvider {
  name = 'mock';
  async complete(req: LLMRequest): Promise<LLMResponse> {
    // Em produção isto seria substituído por RealLLM. Aqui só repassa um
    // texto "gerado" — os agentes já constroem a resposta natural a partir
    // de dados estruturados, então o LLM é usado só como verniz/fallback.
    return { text: req.prompt, model: req.model };
  }
}

/**
 * Esqueleto do adaptador real. Demonstra como o mesmo contrato atende tanto
 * Claude quanto Gemini. NÃO é chamado na demo (rede desabilitada).
 */
export class RealLLM implements LLMProvider {
  name = 'real';
  constructor(
    private keys: { anthropic?: string; google?: string } = {},
  ) {}

  async complete(req: LLMRequest): Promise<LLMResponse> {
    if (req.model.startsWith('claude')) return this.anthropic(req);
    if (req.model.startsWith('gemini')) return this.google(req);
    throw new Error(`Modelo não suportado: ${req.model}`);
  }

  private async anthropic(req: LLMRequest): Promise<LLMResponse> {
    // const res = await fetch('https://api.anthropic.com/v1/messages', {
    //   method: 'POST',
    //   headers: {
    //     'x-api-key': this.keys.anthropic!,
    //     'anthropic-version': '2023-06-01',
    //     'content-type': 'application/json',
    //   },
    //   body: JSON.stringify({
    //     model: req.model,
    //     max_tokens: 1024,
    //     messages: [{ role: 'user', content: req.prompt }],
    //   }),
    // });
    // const data = await res.json();
    // return { text: data.content[0].text, model: req.model };
    throw new Error('RealLLM.anthropic não habilitado neste ambiente');
  }

  private async google(req: LLMRequest): Promise<LLMResponse> {
    // Chamada à API Gemini iria aqui.
    throw new Error('RealLLM.google não habilitado neste ambiente');
  }
}
