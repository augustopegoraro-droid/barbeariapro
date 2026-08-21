# barbearia-app — casca nativa (Capacitor) da Taylor & Thedy

App iOS/Android da **Barbearia Taylor & Thedy**, construído com [Capacitor](https://capacitorjs.com/)
por cima do site público que já está em produção (`https://taylorethedy.com`, `barbearia-public/`,
D-79 a D-84). A WebView aponta para o site remoto (`server.url` em `capacitor.config.ts`) — **não** é
um bundle estático exportado do Next.js.

## O que este projeto é (e o que ele não é)

- **Este diretório não contém UI nem lógica de negócio.** Tudo que o usuário vê — agenda, serviços,
  perfil, avaliação — vive em `barbearia-public/` e é servido ao vivo pelo backend em produção. Mudar
  uma tela, um texto ou um fluxo acontece lá, nunca aqui.
- Este projeto só existe para: (1) empacotar o site numa WebView nativa instalável nas lojas, (2)
  expor capacidades nativas que o navegador/PWA não tem dentro de uma WebView embutida (push via
  Firebase Cloud Messaging, câmera nativa, abrir links externos fora do app, haptics), e (3) fornecer
  ícone/splash/metadados de app nativo.
- **Não é deployado na VM.** Não entra em `docker-compose.app.yml`, não entra em `deploy/update.sh`,
  não tem CI. É só build local, para gerar os artefatos (`.ipa`/`.aab`) que são enviados manualmente
  às lojas.

## Pré-requisitos

- **Node.js** 18+ (o resto do monorepo já usa Node moderno; qualquer LTS recente serve).
- **iOS:** macOS + Xcode (mais recente da App Store) + [CocoaPods](https://cocoapods.org/)
  (`sudo gem install cocoapods` ou `brew install cocoapods`). Só é possível compilar/rodar iOS num Mac.
- **Android:** [Android Studio](https://developer.android.com/studio) + JDK 17 (o próprio Android
  Studio pode instalar um JDK compatível via "Android Studio > Settings > Build Tools > Gradle").

## Build local — passo a passo

```bash
cd barbearia-app
npm install

# Gera os diretórios nativos (ios/, android/) — não versionados, cada dev gera o seu
npx cap add ios
npx cap add android

# Sincroniza config + plugins com os projetos nativos
npx cap sync

# Gera ícone/splash em todas as resoluções a partir de resources/icon.png e resources/splash.png
npx @capacitor/assets generate
npx cap sync

# Abre nos IDEs nativos para rodar em simulador/emulador ou dispositivo real
npx cap open ios      # abre no Xcode
npx cap open android  # abre no Android Studio
```

Depois de qualquer mudança em `capacitor.config.ts` ou nos plugins do `package.json`, rode
`npx cap sync` de novo antes de abrir o IDE.

### Sobre `resources/icon.png` e `resources/splash.png`

- `resources/icon.png` foi copiado de `barbearia-public/public/icon-512.png` (o ícone PWA/manifest já
  usado no site em produção, com o símbolo "T" da fachada real — ver `CLAUDE.md` D-82 e a nota
  `logo-fachada-placa-inexistente`). **Pendência:** esse arquivo é 512×512; o `@capacitor/assets`
  recomenda uma fonte de **1024×1024** para não fazer upscale ao gerar os tamanhos maiores de ícone de
  loja (App Store exige 1024×1024 para o ícone de marketing). Se houver uma versão em resolução maior
  do símbolo "T" (`t-fachada.png` em `barbearia-public/public/` é 746×1334, retrato — não é quadrado,
  precisaria de um recorte/composição antes de virar ícone), trocar `resources/icon.png` por ela antes
  de gerar os assets finais para submissão às lojas. Para desenvolvimento/teste em simulador, o arquivo
  atual já funciona.
- `resources/splash.png` foi gerado localmente (2732×2732, fundo `#0a0b0d` — a mesma cor de fundo da
  marca, D-82) com o ícone centralizado a ~35% da tela. É um placeholder razoável; ajustar se o design
  de splash oficial mudar.

## Antes de rodar em dispositivo real ou publicar

Esta seção documenta a **Fase D** do plano de implementação — responsabilidades do usuário, fora do
escopo deste scaffold. Nada abaixo foi executado; é a lista do que falta para publicar de verdade.

1. **Contas de loja:**
   - [Apple Developer Program](https://developer.apple.com/programs/) — US$ 99/ano.
   - [Google Play Console](https://play.google.com/console/) — US$ 25, pagamento único.

2. **Projeto Firebase** (gratuito) para push nativo via Firebase Cloud Messaging — a Web Push já usada
   no PWA (D-96) não funciona dentro de uma WebView/WKWebView embutida, por isso o app nativo precisa
   de FCM:
   - Criar um projeto no [Firebase Console](https://console.firebase.google.com/).
   - Registrar o app Android (`applicationId` = `com.taylorethedy.app`, o mesmo `appId` deste
     `capacitor.config.ts`) → baixar `google-services.json` → colocar em `android/app/` (não
     versionar — já está no `.gitignore`).
   - Registrar o app iOS (`Bundle ID` = `com.taylorethedy.app`) → baixar `GoogleService-Info.plist` →
     colocar em `ios/App/App/` (não versionar).
   - Gerar uma **service account** do projeto Firebase e configurar `FCM_CREDENTIALS_JSON` (e
     `FCM_PROJECT_ID`) no `.env` da VM do backend — necessário para o backend disparar push nativo
     (ver Fase A do plano em `/Users/apleandro/.claude/plans/zany-waddling-lark.md`, ainda não
     implementada nesta sessão). Pode ser feito antes das contas de loja — destrava push no Android
     primeiro, sem depender da Apple.

3. **Key APNs (`.p8`)** — só depois de ter conta Apple Developer: gerar em
   *Certificates, Identifiers & Profiles > Keys* no portal da Apple, e cadastrar no Firebase Console
   (*Project Settings > Cloud Messaging > Apple app configuration*) para o FCM conseguir entregar push
   no iOS.

4. **Assinatura dos builds:**
   - **Android:** gerar um keystore (`keytool -genkey -v -keystore taylor-thedy.keystore ...`) e
     guardar em local seguro fora do repo (nunca commitar — já coberto pelo `.gitignore`). É exigido
     para gerar o `.aab` de release.
   - **iOS:** certificado de distribuição + provisioning profile, gerenciados pelo Xcode/conta Apple
     Developer (o próprio Xcode pode automatizar isso com "Automatically manage signing").

5. **Fichas das lojas:**
   - Ícone de marketing (1024×1024, sem transparência para a App Store).
   - Screenshots nos tamanhos exigidos por cada loja (vários tamanhos de tela no iOS; pelo menos um
     conjunto de telefone no Android).
   - Descrição curta/longa, categoria, palavras-chave.
   - **Google Play — Data Safety** / **Apple — Privacy Nutrition Labels:** declarar os dados
     efetivamente coletados pelo app — nome, telefone, e-mail e foto do cliente (ver
     `app/api/public.py`/`barbearia-public/` — sessão de cliente por cookie, sem senha, D-79) — e a
     finalidade (agendamento, comunicação sobre o atendimento).
   - **Política de privacidade:** já existe e está publicada em
     [`https://taylorethedy.com/privacidade`](https://taylorethedy.com/privacidade) (D-86/D-87) — usar
     essa URL nos dois formulários de loja.

6. **Conta de teste para revisão:** o app não tem senha (sessão de cliente é só nome + telefone, D-79)
   — preparar instruções claras para o revisor da loja conseguir "entrar" (ex.: um número de telefone
   de teste pré-cadastrado) nas *Notas de revisão* de cada envio.

7. **Riscos de rejeição a observar na revisão:**
   - **App Store Review Guideline 4.2 (Minimum Functionality / "wrapper de site"):** a Apple rejeita
     apps que são só um navegador embutido apontando para um site. Mitigações já no lugar/planejadas:
     rota `/inicio` dedicada ao modo app (diferente da landing de marketing do browser — ver
     `appendUserAgent: 'TTApp/1'` neste `capacitor.config.ts`), push nativo real (não é possível em
     Safari/WebView comum sem o wrapper), câmera nativa para foto de perfil. Isso reduz o risco, mas
     não é garantia — a revisão é subjetiva; ter uma resposta pronta ("por que isto não é só o site
     dentro de um WebView") ajuda se vier rejeição.
   - **App Store Review Guideline 5.1.1 (Data Collection and Storage) / permissões:** o iOS exige
     textos de propósito (`NSCameraUsageDescription`, `NSPhotoLibraryUsageDescription` se aplicável,
     texto de push é coberto pelo próprio prompt do sistema) no `Info.plist` do projeto Xcode gerado
     por `npx cap add ios`. O Capacitor **não** preenche esses textos automaticamente com conteúdo
     significativo — ele cria as chaves com um placeholder genérico (ou pode nem criar, dependendo da
     versão/plugins instalados). **Antes de submeter, abrir `ios/App/App/Info.plist` no Xcode e
     confirmar/editar manualmente:**
     - `NSCameraUsageDescription`: por exemplo, *"Usamos a câmera para você tirar a foto do seu
       perfil."*
     - Push não exige chave no `Info.plist` (o consentimento é o prompt nativo do sistema no primeiro
       uso), mas confirmar que o texto do prompt (configurado no código de solicitação de permissão,
       Fase B do plano) explica o motivo (lembretes de agendamento) de forma clara.
     - Revisar se algum outro plugin instalado (ex. `@capacitor/browser` não exige, mas plugins
       futuros podem) adiciona chaves de uso que também precisam de texto real, não genérico.

## Sequenciamento

Este scaffold (`barbearia-app/`) só faz sentido a partir do momento em que a rota `/inicio` (Fase B do
plano — home dedicada ao "modo app", diferente da landing de marketing) estiver em produção em
`barbearia-public/`. Até lá, `server.url` aponta para uma rota que ainda pode não existir — ajustar
`capacitor.config.ts` se o caminho final for outro.

Ver o plano completo (Fases A a D) em
`/Users/apleandro/.claude/plans/zany-waddling-lark.md`.
