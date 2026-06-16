# Manual da Recepção — Sistema da Barbearia

> Este manual é para quem trabalha na **recepção**. Não precisa saber nada de
> computador além de usar o **navegador** (Google Chrome) e o **WhatsApp**.
> O sistema **já foi instalado** por um técnico. No dia a dia você só **abre o
> navegador e usa**. Os comandos "de terminal" aqui são só para emergências, e
> estão explicados **tecla por tecla**.

---

## ✏️ Preencha estes dados (peça ao técnico)

- Endereço do sistema: **http://localhost:3000**
- Seu e-mail de acesso: ____________________________
- Sua senha: ____________________________
- Caminho da pasta do sistema no computador: ____________________________
  *(o técnico escreve aqui. Ex.: `/Users/barbearia/barbeariapro`)*
- **Suporte técnico:**
  - Nome: ____________________
  - Telefone/WhatsApp: ____________________
  - Horário de atendimento: ____________________

---

## 1. O que é este sistema

É o **programa da barbearia** que fica no computador da recepção. Com ele você:

- **Cadastra clientes** e vê o histórico de cada um.
- **Marca e organiza os agendamentos** dos profissionais.
- Acompanha a **fidelidade** dos clientes (quem vem sempre, quem sumiu).
- Tem um **robô no WhatsApp** que responde os clientes **sozinho**, tira dúvidas
  e ajuda a marcar horário — inclusive fora do expediente.

Em resumo: ele **organiza a agenda**, **guarda os dados dos clientes** e
**atende o WhatsApp automaticamente**, para você não perder cliente nem horário.

---

## 2. Como o sistema funciona (bem por cima)

São **três partes** trabalhando juntas. Pense assim:

1. **O painel** — a tela que **você** abre no navegador para ver clientes e
   agenda. É a sua "mesa de trabalho" digital.
2. **O robô do WhatsApp** — um "atendente automático" que lê e responde as
   mensagens dos clientes no WhatsApp da barbearia, sem você precisar digitar.
3. **O cofre (banco de dados)** — onde **todos os dados ficam guardados**
   (clientes, horários, histórico). Você não vê o cofre; ele trabalha por baixo.

Essas três partes ficam dentro de um programa chamado **Docker** (pense nele como
uma "caixa" que mantém tudo ligado e organizado no computador).

---

## 3. Cuidados importantes — o que NUNCA fazer ⚠️

- **NÃO feche o programa Docker** (o ícone de **baleia** na barra do computador).
  Se fechar, o painel e o robô **param**.
- **NÃO desligue o computador no meio do expediente** sem necessidade.
- **NÃO feche** nenhuma janela preta com letras que esteja aberta (é o robô
  trabalhando).
- **NÃO apague** pastas, arquivos ou ícones do sistema, mesmo que pareçam
  "inúteis".
- **NÃO desconecte** o WhatsApp da barbearia do celular ("Aparelhos conectados").
- **NÃO mexa** em configurações do Docker.

Se aparecer qualquer janela perguntando se quer **atualizar / fechar / apagar**
algo do Docker, **escolha "Não/Cancelar"** e, na dúvida, chame o suporte.

---

## 4. Abrir o sistema de manhã

1. Ligue o computador e espere ele iniciar por completo.
2. Confira se o **Docker está ligado**: procure o ícone de **baleia** na barra
   (em cima, no Mac; embaixo à direita, no Windows). Ele deve estar **parado/verde**,
   não piscando. Se não estiver aberto, abra o **Docker Desktop** pelo ícone de
   aplicativos e espere ~1 minuto.
3. Abra o **Google Chrome**.
4. Digite na barra de endereço: **http://localhost:3000** e aperte **Enter**.
5. Deve aparecer a **tela de login**. Se aparecer, está no ar. 🎉

> Dica: peça ao técnico para deixar **http://localhost:3000** salvo nos
> **favoritos** do Chrome, para você só clicar.

---

## 5. Como entrar (login)

1. No Chrome, vá para **http://localhost:3000** (ele te leva para a tela de login).
2. Digite o seu **e-mail** no primeiro campo.
3. Digite a sua **senha** no segundo campo.
4. Clique em **Entrar**.
5. Deu certo: abre o painel com o **menu** (agenda, clientes, etc.).

**Trocar a senha:** hoje a troca de senha é feita **pelo técnico**. Se quiser
mudar a sua senha, peça ao suporte — ele altera para você em poucos minutos.
**Nunca** compartilhe sua senha por escrito em lugares visíveis.

---

## 6. Confirmar que está tudo funcionando

1. **Painel:** http://localhost:3000 abre e você consegue **fazer login**.
2. **Robô do WhatsApp:** pegue **outro celular** (não o da barbearia) e mande uma
   mensagem para o **número da barbearia**, por exemplo: *"Oi, vocês estão
   abertos?"*. Em alguns segundos o robô deve **responder sozinho**.
   - Respondeu → está tudo certo. ✅
   - Não respondeu em ~1 minuto → veja a **Seção 10** ("o WhatsApp parou de responder").

---

## 7. Uso no dia a dia (o que dá para fazer no painel)

Pelo menu do painel você consegue, entre outras coisas:

- **Clientes:** cadastrar novo cliente, buscar, ver telefone e histórico, marcar
  como bloqueado, ver nível de fidelidade.
- **Agenda / Agendamentos:** ver os horários do dia, marcar, remarcar e cancelar
  atendimentos por profissional.
- **Fidelidade:** ver quais clientes são frequentes, quais estão "em risco" (sem
  vir há um tempo) e quais sumiram — útil para chamar de volta.

> O robô do WhatsApp trabalha **em paralelo**: enquanto você usa o painel, ele
> continua atendendo os clientes no WhatsApp. Os dois mexem no **mesmo cofre**,
> então o que o robô agenda aparece para você e vice-versa.

---

## 8. Encerrar no fim do expediente

**Você NÃO precisa desligar o sistema.** O ideal é **deixar o computador ligado**,
porque o **robô do WhatsApp continua atendendo os clientes à noite e nos fins de
semana**.

- Pode **fechar o navegador** (Chrome) à vontade — isso **não** desliga nada;
  o sistema continua rodando.
- **Não** feche o Docker nem as janelas pretas.
- Se a barbearia tem política de **desligar o PC**, tudo bem: o sistema volta
  sozinho quando ligar de novo (veja a Seção 9). Mas, enquanto desligado, o robô
  **não responde** os clientes.

---

## 9. Se o computador reiniciar ou cair a luz

O sistema foi configurado para **voltar sozinho**. Quando o computador ligar de novo:

1. Espere o computador iniciar por completo (~2 a 3 minutos).
2. Confira a **baleia** do Docker na barra (deve estar ligada).
3. Abra o Chrome e vá em **http://localhost:3000**.
4. Apareceu a tela de login → **está tudo de volta**. ✅
5. Faça o **teste do WhatsApp** da Seção 6.

Se depois de ~5 minutos o painel **não** abrir, use o **Botão de Pânico**
(Seção 11). Se mesmo assim não voltar, **chame o suporte** (Seção 15).

---

## 10. Solução de problemas (para leigos)

> Regra de ouro: tente **uma coisa de cada vez**. Se passar do ponto onde diz
> **"chame o suporte"**, **pare** e chame — não force.

### 10.1 O painel não abre / página de erro
- **O que você vê:** "Não foi possível acessar esse site", ou a página não carrega.
- **Tente:**
  1. Confira se digitou certo: **http://localhost:3000**.
  2. Veja se a **baleia** do Docker está ligada. Se não, abra o Docker Desktop e
     espere 1 minuto. Tente de novo.
  3. Use o **Botão de Pânico** (Seção 11).
- **Quando parar e chamar o suporte:** se depois do Botão de Pânico continuar sem abrir.

### 10.2 A tela fica branca (em branco)
- **O que você vê:** página totalmente branca, sem nada.
- **Tente:**
  1. Atualize a página: aperte **F5** (ou clique no ícone de recarregar 🔄).
  2. Feche o Chrome e abra de novo em **http://localhost:3000**.
  3. Botão de Pânico (Seção 11).
- **Quando chamar o suporte:** se continuar branca após recarregar e reiniciar.

### 10.3 O login não funciona
- **O que você vê:** "usuário ou senha inválidos", ou nada acontece ao clicar Entrar.
- **Tente:**
  1. Confira **Caps Lock** (letra maiúscula travada) e espaços no começo/fim.
  2. Confirme e-mail e senha (campos da página 0 deste manual).
  3. Se tiver certeza da senha e ainda assim não entra → **chame o suporte**
     (a senha pode precisar ser redefinida por ele).
- **Quando chamar o suporte:** senha certa e mesmo assim não entra.

### 10.4 O WhatsApp parou de responder os clientes
- **O que você vê:** clientes dizem que mandaram mensagem e o robô **não respondeu**.
- **Tente:**
  1. Veja se o **celular da barbearia** está ligado, com **internet** e com o
     **WhatsApp aberto**.
  2. No WhatsApp do celular: **Configurações → Aparelhos conectados** — deve haver
     um aparelho conectado (o robô). Se **sumiu**, o robô desconectou → **chame o
     suporte** para reconectar (ele faz pelo QR code).
  3. Confira a internet do computador.
  4. Botão de Pânico (Seção 11) e teste de novo (Seção 6).
- **Quando chamar o suporte:** se o aparelho conectado sumiu, ou se após o Botão
  de Pânico o robô continuar mudo.

### 10.5 Apareceu uma mensagem de erro na tela
- **O que você vê:** uma caixa ou texto vermelho com um erro.
- **Tente:**
  1. **Não clique em nada às pressas.** Tire uma **foto/print** da tela inteira.
  2. Recarregue a página (**F5**).
  3. Se atrapalhar o trabalho, use o Botão de Pânico (Seção 11).
- **Quando chamar o suporte:** mande a foto do erro junto (Seção 15).

### 10.6 A internet caiu
- **O que você vê:** nada carrega, navegador reclama de conexão.
- **Tente:**
  1. Confirme que **outros sites** também não abrem (aí é a internet mesmo).
  2. Reinicie o **roteador** (tire da tomada, espere 30s, ligue).
  3. Quando a internet voltar, o sistema continua funcionando; só **teste o
     WhatsApp** (Seção 6) porque o robô fica mudo sem internet.
- **Quando chamar o suporte:** problema de internet é com a **operadora**, não com
  o sistema. Chame o suporte só se, **com internet de volta**, o robô não responder.

### 10.7 O computador foi desligado sem querer
- **Tente:** siga a **Seção 9** (ligar e conferir). É normal e o sistema volta sozinho.
- **Quando chamar o suporte:** se não voltar após o Botão de Pânico.

---

## 11. 🆘 Botão de Pânico (reiniciar o sistema)

Use quando o **painel travou** ou o **robô parou** e nada acima resolveu. Isto
**reinicia o sistema sem apagar nenhum dado**. Faça **com calma**, na ordem:

### Passo 1 — Abrir o Terminal
- **No Mac:** aperte **Command (⌘) + barra de espaço**, digite **`Terminal`** e
  aperte **Enter**. Vai abrir uma **janela preta com letras**.
- **No Windows:** clique no menu Iniciar, digite **`PowerShell`** e aperte **Enter**.

### Passo 2 — Entrar na pasta do sistema
Digite a palavra **`cd`**, depois um **espaço**, depois o **caminho da pasta**
(o que está anotado na página 0 deste manual). Exemplo:
```
cd /Users/barbearia/barbeariapro
```
Aperte **Enter**. (Se você não tem certeza do caminho, **pare e chame o suporte**.)

### Passo 3 — Digitar o comando de reiniciar (exatamente assim)
```
docker compose -f docker-compose.app.yml restart
```
Aperte **Enter**.

### Passo 4 — Esperar
Vão aparecer várias linhas escritas. **Espere** até parar de escrever e o cursor
voltar (uns 20–40 segundos). **O que aparece quando dá certo:** linhas como
`Container barbeariapro-app-backend Started` e
`Container barbeariapro-app-frontend Started`.

### Passo 5 — Confirmar que voltou
- Volte ao Chrome, vá em **http://localhost:3000** e aperte **F5**.
- Apareceu a tela de login → **resolvido**. ✅
- Faça o teste do WhatsApp (Seção 6).

> **Se o robô continuar mudo** mesmo após o painel voltar, reinicie também a parte
> do robô. No mesmo Terminal, na mesma pasta, digite:
> ```
> docker compose restart
> ```
> e aperte **Enter**. Espere terminar e teste de novo. Se não resolver, **chame o
> suporte** (Seção 15) e mande os logs (Seção 15).

---

## 12. Perguntas frequentes (FAQ)

**1. Esqueci minha senha. E agora?**
Chame o suporte. Hoje quem redefine senha é o técnico. Em poucos minutos ele
resolve.

**2. Posso desligar o computador à noite?**
Pode, mas o robô do WhatsApp **fica mudo** enquanto desligado. O ideal é deixar
ligado. Se desligar, ao ligar de novo o sistema volta sozinho.

**3. Posso fechar o navegador (Chrome)?**
Pode, sempre. Fechar o navegador **não desliga** o sistema. É só reabrir em
http://localhost:3000 quando precisar.

**4. Apareceu uma tela preta com letras. O que é?**
É o sistema/robô trabalhando. **Não feche.** Só use o Terminal quando o manual
mandar (Botão de Pânico, Seção 11).

**5. O cliente disse que não recebeu a confirmação no WhatsApp.**
Verifique: (a) o número que ele mandou é o **número certo** da barbearia? (b) o
celular da barbearia está **ligado e com internet**? (c) faça o teste da Seção 6.
Se o robô não responder nem no teste, veja a Seção 10.4.

**6. O robô respondeu uma coisa errada/estranha para o cliente.**
Anote o que aconteceu (print da conversa) e avise o suporte. Você pode responder
manualmente pelo WhatsApp normal nesse meio tempo.

**7. Posso responder o cliente manualmente pelo WhatsApp?**
Pode. O robô e você usam o **mesmo número**. Se você responder, ótimo — só evite
"brigar" com o robô respondendo a mesma coisa ao mesmo tempo.

**8. O painel está lento. É problema?**
Tente recarregar (**F5**). Se continuar lento, veja se o computador está
sobrecarregado (muitos programas abertos). Persistindo, avise o suporte.

**9. Posso instalar outros programas nesse computador?**
Evite. Programas pesados podem deixar o sistema lento ou instável. Combine com o
suporte antes.

**10. Posso usar esse computador para navegar/imprimir?**
Para tarefas leves, sim. Só **não feche o Docker** nem as janelas do sistema.

**11. A baleia (Docker) sumiu da barra. E agora?**
Abra o **Docker Desktop** pelos aplicativos e espere ~1 minuto. Depois teste o
painel. Se não voltar, chame o suporte.

**12. Cliquei sem querer em fechar o Docker. O que faço?**
Abra o Docker Desktop de novo e espere ~1–2 minutos. Os programas voltam sozinhos.
Teste o painel (Seção 6).

**13. Apareceu "Não foi possível acessar esse site".**
Veja a Seção 10.1. Geralmente é o Docker desligado ou precisa do Botão de Pânico.

**14. A tela ficou branca.**
Seção 10.2: aperte **F5**, reabra o Chrome, e se preciso o Botão de Pânico.

**15. Cadastrei um cliente errado. Dá para corrigir?**
Sim, pelo painel, na parte de **Clientes**: busque o cliente e edite os dados.

**16. Marquei um horário errado.**
Pelo painel, na **Agenda/Agendamentos**, é possível remarcar ou cancelar.

**17. O número de WhatsApp da barbearia mudou. O que fazer?**
Isso exige o técnico reconectar o novo número (pelo QR code). Chame o suporte.

**18. O WhatsApp pediu para "reconectar aparelho".**
Quem reconecta é o técnico (ele lê o QR code). Chame o suporte.

**19. Posso mexer no programa "n8n" ou "Evolution"?**
Não. São as engrenagens do robô. **Não mexa.** Só o técnico mexe.

**20. Apareceu uma atualização do Docker pedindo para instalar.**
Escolha **"Mais tarde/Cancelar"** e avise o suporte. Atualizar na hora errada pode
parar o sistema.

**21. O sistema usa internet o tempo todo?**
Sim. O robô precisa de internet para conversar no WhatsApp e para a inteligência
artificial. Sem internet, o painel ainda abre, mas o robô fica mudo.

**22. Perdi a conexão por uns minutos. Os dados se perdem?**
Não. Os dados ficam guardados no "cofre". Quando a internet volta, tudo continua.

**23. Como sei se o robô está realmente ligado?**
Faça o teste da Seção 6 (mandar uma mensagem de outro celular).

**24. O computador reiniciou sozinho de madrugada (atualização do Windows).**
De manhã, siga a Seção 9. O sistema costuma voltar sozinho.

**25. Posso ter o sistema aberto em dois computadores?**
O painel pode ser aberto em mais de um navegador/computador na mesma rede, se o
técnico configurou. Na dúvida, pergunte ao suporte.

**26. Esqueci de fazer backup. Tem problema?**
O backup é responsabilidade combinada com o técnico (geralmente automático).
Se você não faz backup manualmente, tudo bem — confirme com o suporte que o
backup automático está ativo.

**27. Apareceu texto em inglês na tela preta. É erro?**
Nem sempre. Muitas linhas em inglês são normais. Só é problema se o painel não
abrir. Em caso de dúvida, tire um print e mande ao suporte.

**28. Cliquei em "Entrar" e a página ficou "rodando" e não entra.**
Espere uns 10 segundos. Se não entrar, recarregue (**F5**) e tente de novo. Se
persistir, Seção 10.3.

**29. Posso desligar só o monitor e deixar o computador ligado?**
Sim! Desligar **só o monitor** é ótimo: economiza energia e o robô continua
atendendo.

**30. O antivírus reclamou do Docker.**
Não bloqueie o Docker. Avise o suporte para liberar (colocar na lista de exceções).

**31. Como faço para o cliente falar com uma pessoa e não com o robô?**
Você pode entrar na conversa pelo WhatsApp normal a qualquer momento e responder
manualmente.

**32. A luz caiu e voltou. Preciso fazer algo?**
Siga a Seção 9. Confira a baleia do Docker e teste o painel e o WhatsApp.

---

## 13. ✅ Checklist de abertura (todo dia de manhã)

- [ ] Computador ligado e iniciado por completo.
- [ ] Ícone da **baleia (Docker)** ligado na barra.
- [ ] Chrome aberto em **http://localhost:3000** mostrando a tela de login.
- [ ] **Login** feito com sucesso.
- [ ] **Teste do WhatsApp** (Seção 6): robô respondeu.
- [ ] Celular da barbearia ligado, com internet e WhatsApp aberto.

---

## 14. 🌙 Checklist de encerramento (fim do dia)

- [ ] Pode **fechar o Chrome** (opcional).
- [ ] **NÃO** fechar o Docker nem as janelas pretas.
- [ ] **Deixar o computador ligado** (recomendado, para o robô atender à noite).
- [ ] Se a regra da barbearia for desligar: desligue normalmente — amanhã siga o
      checklist de abertura.
- [ ] Celular da barbearia carregando e com internet.

---

## 15. Quando e como chamar o suporte

**Chame o suporte quando:** o manual mandou ("pare e chame o suporte"), ou quando
algo importante não funciona e você já tentou o Botão de Pânico (Seção 11).

**O que mandar na mensagem para o suporte** (copie e preencha):
```
- O que aconteceu (com suas palavras):
- A que horas começou:
- O que aparece na tela (mande FOTO/PRINT):
- O painel abre? (sim/não)
- O robô do WhatsApp responde? (sim/não)
- Já tentei o Botão de Pânico? (sim/não)
```

**Coletar os "logs" (relatório técnico) para enviar:**
Os logs ajudam o suporte a entender o problema. Para gerar:

1. Abra o **Terminal** e entre na pasta do sistema (Seção 11, Passos 1 e 2).
2. Digite **exatamente**:
   ```
   docker compose -f docker-compose.app.yml logs --tail=200 > logs-app.txt
   ```
   e aperte **Enter**. (Cria um arquivo `logs-app.txt` na pasta.)
3. Em seguida digite:
   ```
   docker compose logs --tail=200 > logs-infra.txt
   ```
   e aperte **Enter**. (Cria `logs-infra.txt` — logs do robô.)
4. **O que aparece quando dá certo:** o cursor volta sem mensagem de erro, e os
   dois arquivos passam a existir na pasta.
5. **Envie os arquivos** `logs-app.txt` e `logs-infra.txt` para o suporte, junto
   com a foto da tela e o texto preenchido acima.

> **Erro comum:** "no such file or directory" ou "not found" ao digitar o comando.
> Geralmente é porque você **não está na pasta certa** (refaça o Passo 2 da Seção
> 11) ou **digitou o comando com algum erro** (copie exatamente). Se não
> conseguir, tire um print da janela preta e mande assim mesmo para o suporte.

**Dados do suporte (preencha):**
- Nome: ____________________
- Telefone/WhatsApp: ____________________
- Horário de atendimento: ____________________
