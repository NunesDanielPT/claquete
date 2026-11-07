# Claquete
Organizador de eventos, clientes e faturas para freelancers de audiovisual (PC e telemóvel).
Não emite faturas: só controla datas, valores e estado (por faturar / faturada / paga).
Cada utilizador só vê os seus dados. Só biblioteca standard do Python + SQLite.

## Deploy no Portainer
Stacks > Add stack > Repository > URL deste repo, `docker-compose.yml`.
Usa a rede Docker já existente `networkpi` (tem de existir antes do deploy).
Variáveis de ambiente (todas opcionais, definem-se no Portainer, nunca no GitHub):

| Variável | Para quê |
|---|---|
| `BASE_URL` | Endereço do site, ex.: `http://192.168.0.47:8085`. Necessário para os links dos emails. |
| `SMTP_USER` | O teu Gmail usado só para enviar (ex.: `claquete.envio@gmail.com`). |
| `SMTP_PASSWORD` | "Palavra-passe de app" do Gmail (16 letras), não a palavra-passe normal. |
| `INVITE_CODE` | Código de convite inicial (depois muda-se no Admin). |
| `ADMIN_USER` | Opcional: utilizador que fica administrador. O primeiro registo já é admin. |

Emails enviados: boas-vindas no registo e link de recuperação de palavra-passe.
Sem `SMTP_USER`/`SMTP_PASSWORD`/`BASE_URL`, o link de recuperação aparece nos Logs do container.

## Gmail: palavra-passe de app
1. Na conta Gmail de envio, ativa a verificação em 2 passos.
2. Em https://myaccount.google.com/apppasswords cria uma palavra-passe de app (nome: Claquete).
3. Copia as 16 letras para `SMTP_PASSWORD` no Portainer.

## Backup
docker run --rm -v claquete_data:/data -v $PWD:/b alpine tar czf /b/backup.tgz -C /data .

## Idiomas
Português, English, Español, Français e Italiano. O site usa o idioma do browser do visitante (ou o que ele escolher no rodapé / em Conta) e, se não houver correspondência, o idioma por defeito (Admin > Site).
As traduções estão em `i18n.py`: para corrigir uma frase edita a linha respetiva (português, inglês, espanhol, francês, italiano). O texto escrito pelos utilizadores nunca é traduzido.

## Suporte e Sobre
- Botão **Suporte** nas páginas de entrada/registo (visitantes: nome e email obrigatórios) e no rodapé; quem tem conta usa os dados da conta.
- As mensagens chegam a **Admin > Suporte** (com contador de novas). Respondes lá; a resposta aparece na conversa do utilizador (ou no link da conversa, para visitantes) e é enviada por email se o SMTP estiver configurado. Também recebes um email de cada mensagem nova.
- Página **Sobre** (`/about`) explica para que serve o site e quem o fez.

## IVA, retenção e Segurança Social

Cada evento tem **IVA** (23/13/6 %, sem IVA ou autoliquidação) e **retenção na fonte de IRS**. Em Conta → *Faturação e impostos* defines os valores predefinidos (país, IVA, retenção, Segurança Social). Nas Estatísticas há uma tabela de impostos por trimestre e uma estimativa da Segurança Social (taxa × % do rendimento, por defeito 21,4 % × 70 %). São valores indicativos, não substituem o contabilista.

## Chat em tempo real

- Servidor WebSocket próprio (sem dependências) no mesmo porto: mensagens instantâneas, "online / visto por último", "a escrever…", ✓ enviado / ✓✓ lido e contadores de não lidas.
- Interface tipo WhatsApp/Telegram: lista com separadores **Conversas · Contactos · Grupos**, pesquisa, ponto verde de presença e mensagens não lidas.
- Emojis e imagens no chat (também em grupos). As imagens são guardadas na base de dados e **apagadas ao fim de 5 dias** (a mensagem fica com "Imagem expirada").
- A presença (anel verde à volta da foto) funciona também sem WebSocket, com atualização a cada ~15 s.
- Se o WebSocket falhar, o chat continua a funcionar por polling.
- **Reverse proxy:** tem de deixar passar WebSockets. No Nginx Proxy Manager, ativa **"Websockets Support"** no Proxy Host. Em Nginx puro: `proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600s;`.

## Novidades (admin → todos)

No Admin → **Novidades**, escreve um título e uma mensagem (ex.: "UPDATE 3.0"), com traduções opcionais. Todos os utilizadores recebem um aviso instantâneo, um contador no sino e a lista em **Novidades**. Vês quantos já leram.

## Foto de perfil

Em Definições → Foto de perfil. A imagem é reduzida no browser (256×256) e guardada em base64 na base de dados (sem ficheiros).

## Admin
A primeira conta registada é administradora. Ícone **Admin** no menu: resumo e avisos, contas (editar email, repor password, suspender, apagar), mensagens de suporte, apagar contas (também várias de uma vez), promover administradores pesquisando por utilizador ou email, nome/cores/textos do site, publicidade, backups (automático diário em `/data/backups`), restauro e consola SQL.

## Tema e exportação
- Definições → Aspeto: automático, claro (dia) ou escuro (noite).
- Estatísticas → Exportar (ou ligações nos eventos e clientes): PDF/Excel por evento, cliente, mês ou intervalo de datas. Gerado em `export.py`, sem bibliotecas externas. Não é uma fatura.

## AV Freelancers (rede)
Perfil profissional opcional (Definições → Perfil profissional, ou menu AV Freelancers): funções, cidade, disponibilidade para viajar, software, equipamento e carreira. Só aparece na pesquisa se o utilizador ativar «visível». Mensagens passam pelo chat (a primeira mensagem segue num pedido de amizade); email/telemóvel só são partilhados após autorização. Lógica e listas em `people.py` (Dockerfile já copia `*.py`).

## Envio de faturas por email
Definições → Envio de faturas por email: cada utilizador liga o seu SMTP (Gmail com palavra-passe de aplicação, Outlook, etc.), define a mensagem por omissão e envia a partir do evento (anexa o PDF da fatura emitida e, opcionalmente, o resumo do Claquete). A palavra-passe fica cifrada na base de dados (chave derivada do segredo interno). Só se envia para os emails guardados na ficha do cliente, com limite de 30 envios por hora por utilizador. As faturas anexadas ficam na base de dados (incluídas nas cópias de segurança). O servidor tem de poder sair para as portas 587/465. Lógica em `mailer.py`.

## Email do sistema no painel
Admin → Email: servidor, porta, segurança, utilizador, palavra-passe (cifrada) e endereço do remetente, com botão de teste. O que for guardado aí tem prioridade sobre `SMTP_USER`/`SMTP_PASSWORD` do Portainer; «Voltar às variáveis do Portainer» apaga a configuração do painel.

## Estados dos eventos
**Por realizar** (ainda não terminaram: data de fim posterior a hoje e sem fatura) → **Por faturar** (já terminaram e não têm fatura) → **Faturada** → **Paga**. Um evento só entra em «Por faturar» a partir do dia em que termina. Há um separador «Por realizar» na página Eventos e a mesma opção no filtro de exportação.
