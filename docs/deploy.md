# Colocando a Lumio no ar

Este guia sobe a Lumio num servidor Linux com HTTPS, usando os arquivos
`docker-compose.prod.yml` e `deploy/`. Leva uns 30 minutos, mais o tempo de
o domínio propagar.

## Do que você precisa

| Item | Sugestão | Custo aproximado* |
| --- | --- | --- |
| Servidor (VPS) com Ubuntu 24.04, 2 vCPU, 4 GB de RAM, 40 GB de disco | Hetzner CX22, DigitalOcean, Vultr, Magalu Cloud, Oracle Cloud (camada gratuita) | de R$ 0 a R$ 60/mês |
| Um domínio ou subdomínio | registro.br (`.com.br`), ou um subdomínio de um domínio que você já tem | ~R$ 40/ano |
| Conta num serviço de e-mail transacional (SMTP) | Brevo (plano grátis de 300 e-mails/dia), Amazon SES, Resend | grátis no volume do MVP |

\* Preços mudam; confira no site de cada um. Os testes da sprint 6
(`docs/resultados.md`) mostram quanto de CPU e memória a Lumio usa: 4 GB de
RAM sobram para o MVP.

## Passo a passo

### 1. Servidor

Crie a VPS com Ubuntu 24.04 e entre por SSH. Depois:

```bash
# firewall: só SSH, HTTP e HTTPS
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443 && sudo ufw enable

# Docker (script oficial) e permissão para o seu usuário
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker compose version          # precisa ser 2.24 ou mais novo
```

### 2. Domínio

No painel do seu domínio, crie um registro **A** apontando
`lumio.seudominio.com.br` para o IP da VPS. Confira (pode levar alguns minutos):

```bash
dig +short lumio.seudominio.com.br      # tem que mostrar o IP da VPS
```

### 3. Código e configuração

```bash
sudo mkdir -p /opt/lumio && sudo chown $USER /opt/lumio
git clone https://github.com/JoaoRuy777/lumio.git /opt/lumio
cd /opt/lumio
./deploy/gen-env.sh lumio.seudominio.com.br voce@seudominio.com.br
nano .env       # preencha SMTP_HOST, SMTP_USER, SMTP_PASSWORD e SMTP_FROM
```

Se o repositório for privado, o `git clone` pede login: use um *personal
access token* do GitHub como senha, ou `gh auth login`.

O `gen-env.sh` cria senhas e chaves aleatórias, com permissão 600. **Guarde
uma cópia do `.env` num lugar seguro** (gerenciador de senhas): sem o
`LUMIO_SECRET_KEY`, as communities SNMP salvas não abrem mais.

**E-mail:** no serviço de SMTP, verifique o domínio do remetente (registros
SPF e DKIM que ele indicar). Sem isso, os alertas caem no spam.

### 4. Subir

Para a **apresentação do TCC** (com as OLTs simuladas):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile demo up -d --build
```

Para **OLTs reais**, sem `--profile demo` (leia antes a seção "OLTs reais").

Acompanhe a subida e o certificado HTTPS:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy   # "certificate obtained"
```

### 5. Conferir

1. Abra `https://lumio.seudominio.com.br` e crie a conta do provedor.
2. Modo demo: **Nova OLT** com endereço `simulator`, porta `16101`,
   community `public` → **Testar conexão** → **Salvar**.
3. **Notificações** → **Novo canal** com o seu e-mail → **Enviar teste**.
   Chegou? O SMTP está certo.
4. Para mostrar uma falha ao vivo na banca, o simulador não fica exposto
   na internet. Rode no servidor:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec simulator \
     python -c "import urllib.request,json; urllib.request.urlopen(urllib.request.Request('http://localhost:8080/scenarios', json.dumps({'type':'fiber_cut','olt':'olt-centro','pon':'0/1/2'}).encode(), {'content-type':'application/json'}))"
   ```

   Para voltar ao normal, troque o corpo por `{'type':'reset'}`.

### 6. Rotina

```bash
# backup diário do banco às 3h (guarda os 14 últimos em /opt/lumio/backups)
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/lumio/deploy/backup.sh >> /opt/lumio/backups/backup.log 2>&1") | crontab -

# atualizar para a versão nova do main (as migrações do banco rodam sozinhas)
cd /opt/lumio && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail 100 api worker notifier
```

Copie os backups para fora do servidor de vez em quando (ex.: `scp` para o
seu computador, ou um bucket). Backup que só existe no próprio servidor some
junto com ele.

## OLTs reais

As OLTs ficam na rede interna do provedor; a Lumio na nuvem precisa
**alcançá-las por SNMP (UDP 161)** e **receber as traps (UDP 162)**. Nunca
exponha o SNMP das OLTs na internet. O caminho recomendado é uma VPN
**WireGuard** entre a VPS e o roteador do provedor (MikroTik e a maioria
dos roteadores atuais suportam):

1. Suba o WireGuard na VPS (`sudo apt install wireguard`) e no roteador do
   provedor, liberando pelo túnel só a rede de gerência das OLTs.
2. Nas OLTs: community SNMP **somente leitura**, liberada só para o IP da
   VPS no túnel; destino de trap = IP da VPS no túnel, porta 162.
3. Publique a porta de traps só na interface do túnel, num arquivo
   `docker-compose.override.yml` (troque `10.10.0.1` pelo IP da VPS no túnel):

   ```yaml
   services:
     collector:
       ports:
         - "10.10.0.1:162:1162/udp"
   ```

   e suba incluindo esse arquivo (`-f docker-compose.override.yml`).
4. No painel, cadastre a OLT com o IP de gerência dela e use **Testar conexão**.

Com vários provedores, cada um precisa do seu túnel. Para escalar, o passo
seguinte (fora do MVP) é rodar um coletor dentro de cada provedor, enviando
os dados para a nuvem por HTTPS.

## Vercel (parcial, não testado)

O `vercel.json` publica só **o painel (`web`) e a API (`api`)**, no mesmo
domínio: `/api/*` vai para a API e o resto para o painel. Coletor, worker,
notificador e simulador **não rodam na Vercel** (são processos contínuos e o
coletor recebe traps por UDP), então, sem um servidor para eles, a Lumio
abre as telas mas não coleta nem gera alarmes.

O que configurar no projeto da Vercel:

1. **Postgres no Neon** (seção abaixo). Para outro provedor, rode as
   migrações com `DATABASE_URL=<url do admin>` e confira se ele permite criar
   o papel `lumio_system` com `BYPASSRLS`.
2. **Variáveis de ambiente** do serviço `api`: `DATABASE_URL` =
   `LUMIO_API_DATABASE_URL` do `.env.lumio.local` (pooled, papel `lumio_app`),
   `LUMIO_JWT_SECRET`, `LUMIO_SECRET_KEY`, `LUMIO_SERVICE_TOKEN` (do mesmo
   arquivo) e, opcional, `REDIS_URL` (ex.: Upstash) para o tempo real; sem ele
   o painel atualiza a cada 30 s.
3. Teste com `vercel dev` e depois um deploy de *preview*. A conferir no
   primeiro teste: as rotas do painel (ex.: abrir `/olts/<id>` direto) caírem
   no `index.html`, e o "Testar conexão" da API alcançar a OLT (a Vercel não
   está na rede do provedor).

O restante (simulador, coletor, worker e notificador) roda com o
`docker-compose.coleta.yml`, numa máquina com Docker: o seu computador (na
apresentação) ou uma VPS (ligado o tempo todo). Ele usa o mesmo Neon e o
mesmo Redis da Vercel e lê as OLTs da API da Vercel:

```bash
# no .env.lumio.local: LUMIO_API_URL="https://seu-projeto.vercel.app" e REDIS_URL="rediss://..."
docker compose --env-file .env.lumio.local -f docker-compose.coleta.yml up -d --build
```

No painel, cadastre as OLTs simuladas com endereço `simulator`, portas `16101` a
`16105` (`simulator/config/rede-demo.yaml`), community `public`. A descoberta roda na Vercel, que não
enxerga o simulador, então a OLT é salva com "sem resposta" e as ONUs
aparecem na primeira coleta (até 1 minuto). Falhas para a demonstração:
`http://localhost:8080/docs` → `POST /demo/{caso}` (`criticos` provoca todos os tipos de alarme;
`normalizar` volta ao normal); e-mails:
`http://localhost:8025`.

## Banco no Neon

O projeto Neon está descrito em `neon.ts` (região São Paulo, `sa-east-1`).

```bash
npm i -g neon@latest && neon login
neon deploy                     # cria o banco e grava .env.local (fora do git)
docker compose run --rm --no-deps tests python scripts/neon_setup.py
```

O `neon_setup.py` gera o `.env.lumio.local` (fora do git; guarde uma cópia)
com as senhas dos papéis e as chaves da Lumio, aplica as migrações pela
conexão **direta** e escreve as URLs de cada serviço:

| Serviço | Variável | Conexão |
| --- | --- | --- |
| API (Vercel ou servidor) | `LUMIO_API_DATABASE_URL` | pooled (`-pooler`), papel `lumio_app`, sujeito ao RLS |
| worker e notificador | `LUMIO_SYSTEM_DATABASE_URL` | direta, papel `lumio_system` |

Na conexão pooled (PgBouncer em modo transação) a API desliga o cache de
prepared statements do asyncpg sozinha; o `app.tenant_id` já é por transação.

Para rodar a stack local usando o Neon no lugar do Postgres do compose:

```bash
docker compose --env-file .env.lumio.local -f docker-compose.yml -f docker-compose.neon.yml up -d --build
```

**Deixe o worker perto do banco.** Ele faz várias consultas em sequência por
alarme. Do computador de desenvolvimento até o Neon a ida e volta foi de ~130
ms, e cada alarme levou ~2 s para gravar (no Postgres local, ~10 ms). Num
servidor em São Paulo, na mesma região do banco, a ida e volta deve cair para
poucos milissegundos.

## Checklist de segurança

- [ ] `.env` gerado pelo `gen-env.sh`, com permissão 600 e cópia guardada fora do servidor
- [ ] Firewall só com 22, 80 e 443 (e a porta do WireGuard, se usar)
- [ ] SSH só com chave (`PasswordAuthentication no` em `/etc/ssh/sshd_config`)
- [ ] `LUMIO_WEBHOOK_ALLOW_PRIVATE` fica `false` (o `docker-compose.prod.yml` já força)
- [ ] Backup diário configurado e testado (restaurar uma vez, numa máquina de teste)
- [ ] Atualizações do Ubuntu: `sudo apt install unattended-upgrades`

## Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| Caddy não obtém o certificado | DNS ainda não aponta para a VPS, ou portas 80/443 fechadas no firewall da nuvem (além do `ufw`, muitos provedores têm um firewall no painel) |
| `required variable ... is missing` ao subir | Falta a variável no `.env` (a mensagem diz qual) |
| E-mail de teste "Falhou" na tela de Notificações | SMTP errado; passe o mouse sobre "Falhou" para ver o erro |
| E-mail chega no spam | Domínio do remetente sem SPF/DKIM verificados no serviço de SMTP |
| Topo do painel mostra "Sem tempo real" | Proxy na frente do Caddy cortando conexões longas; o painel continua atualizando a cada 30 s |
| OLT real "Sem resposta" | Sem rota pelo túnel, community errada ou ACL da OLT bloqueando o IP da VPS |
