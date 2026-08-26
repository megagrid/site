# MEGAGRID — Guia de Deploy

Do zero ao ar em 5 passos. Tempo total estimado: 20 minutos.

---

## Pré-requisitos

| O que | Onde criar | Plano gratuito |
|---|---|---|
| Conta GitHub | github.com | ✅ |
| Conta Vercel | vercel.com | ✅ (Hobby) |
| Conta Brevo | brevo.com | ✅ até 300 e-mails/dia |
| Domínio megagrid.com.br | registro.br | R$ 40/ano |
| Conta GoatCounter (analytics) | goatcounter.com | ✅ |

---

## Passo 1 — GitHub: criar repositório e subir o código

### 1a. Crie o repositório
1. Acesse **github.com → New repository**
2. Nome: `site` (dentro da org `megagrid`)
3. Visibilidade: **Private** (ou Public — tanto faz para o Vercel funcionar)
4. Não inicialize com README (vamos subir nosso próprio código)
5. Clique em **Create repository**
6. Copie a URL do repositório: `https://github.com/megagrid/site.git`

### 1b. Suba o código
Abra o Terminal na pasta `Megagrid/` e execute:

```bash
# Na pasta raiz do projeto (onde está o vercel.json)
git init
git add .
git commit -m "feat: Megagrid v1 — site dinâmico com robô de dados e 4 calculadoras"
git branch -M main
git remote add origin https://github.com/megagrid/site.git
git push -u origin main
```

> **Dica**: se o Terminal pedir autenticação, use um Personal Access Token (PAT).
> Crie em: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
> Permissão necessária: `Contents: Read and write` no repositório criado.

---

## Passo 2 — Vercel: conectar e fazer deploy

1. Acesse **vercel.com → Add New → Project**
2. Selecione **"Import Git Repository"** e conecte sua conta GitHub
3. Selecione o repositório `megagrid/site`
4. Nas configurações de build:
   - **Framework Preset**: Other
   - **Root Directory**: `.` (raiz — deixe em branco)
   - **Build Command**: *(deixe vazio)*
   - **Output Directory**: `site` ← **importante**
5. Clique em **Deploy**

O Vercel vai detectar o `vercel.json` automaticamente. Em ~30 segundos o site estará no ar com uma URL `.vercel.app`.

### 2a. Adicionar variáveis de ambiente no Vercel

Acesse: **Vercel → seu projeto → Settings → Environment Variables**

| Nome | Valor | Ambiente |
|---|---|---|
| `BREVO_API_KEY` | sua API key do Brevo (Passo 3) | Production, Preview |
| `BREVO_LIST_ID` | ID da lista no Brevo (Passo 3) | Production, Preview |
| `GOATCOUNTER_API` | seu token GoatCounter (Passo 5) | Production |
| `GOATCOUNTER_SITE` | ex: `megagrid` | Production |

> Após adicionar as variáveis, clique em **Redeploy** para que entrem em vigor.

---

## Passo 3 — Brevo: configurar a newsletter

### 3a. Criar conta e lista
1. Acesse **brevo.com → Criar conta gratuita**
2. No painel: **Contacts → Lists → Create a list**
3. Nome da lista: `Megagrid Newsletter`
4. Copie o **ID da lista** (número exibido na URL ou na coluna ID)

### 3b. Criar API Key
1. **Settings → SMTP & API → API Keys**
2. Clique em **Generate a new API key**
3. Nome: `site`
4. Copie a chave e cole na variável `BREVO_API_KEY` no Vercel (Passo 2a)

### 3c. Configurar double opt-in (recomendado)
1. **Contacts → Automation → Subscription confirmed**
2. Ative o e-mail de confirmação automático para novos inscritos
3. Customize o template com a identidade do Megagrid

> O plano gratuito permite **300 e-mails/dia** — suficiente para começar.
> Para escalar: Starter a partir de €9/mês.

---

## Passo 4 — registro.br: comprar o domínio megagrid.com.br

1. Acesse **registro.br**
2. Pesquise `megagrid.com.br`
3. Se disponível: clique em **Registrar** (R$ 40/ano)
4. Complete com seus dados (CPF/CNPJ)
5. Após ativação (~minutos), configure os DNS:

### 4a. Apontar domínio para o Vercel
No registro.br → Gerenciar domínio → DNS:

| Tipo | Nome | Valor |
|---|---|---|
| A | `@` | `76.76.21.21` |
| CNAME | `www` | `cname.vercel-dns.com` |

No Vercel → projeto → **Settings → Domains**:
- Clique em **Add**
- Digite `megagrid.com.br`
- Repita para `www.megagrid.com.br`

> SSL/HTTPS é configurado automaticamente pelo Vercel via Let's Encrypt.
> Propagação DNS pode levar até 24h, mas geralmente fica pronto em minutos.

---

## Passo 5 — GoatCounter: analytics de cliques (+ Lidas)

O GoatCounter alimenta o ranking "+ Lidas da semana" via API.

### 5a. Criar conta
1. Acesse **goatcounter.com → Create account**
2. Escolha seu subdomínio: `megagrid.goatcounter.com`
3. Copie o código de tracking

### 5b. Adicionar ao site
Adicione antes do `</body>` no `site/index.html`:

```html
<script data-goatcounter="https://megagrid.goatcounter.com/count"
        async src="//gc.zgo.at/count.js"></script>
```

### 5c. API Key para o robô
1. GoatCounter → **Settings → API tokens → Create token**
2. Cole o token na variável `GOATCOUNTER_API` no Vercel
3. Cole `megagrid` (seu subdomínio) em `GOATCOUNTER_SITE`

---

## Passo 6 — GitHub Actions: ativar o robô de dados

### 6a. Verificar que os secrets estão configurados
No repositório GitHub: **Settings → Secrets and variables → Actions**

Adicione se ainda não estiverem:

| Secret | Valor |
|---|---|
| `GOATCOUNTER_API` | token GoatCounter |
| `GOATCOUNTER_SITE` | `megagrid` |

*(O `GITHUB_TOKEN` é automático — não precisa configurar)*

### 6b. Primeira execução manual
1. No GitHub: **Actions → Megagrid — Robô de Dados → Run workflow**
2. Clique em **Run workflow** (branch: main)
3. Aguarde ~2 minutos
4. Verifique se os arquivos `site/data/*.json` foram atualizados no commit

A partir daí, o robô roda automaticamente **2x por dia — 09h e 16h30 BRT**, nas edições da manhã e do fim da tarde.
Cada execução faz commit dos JSONs atualizados → Vercel detecta o push → redeploy automático em ~30s.

---

## Checklist de verificação pós-deploy

- [ ] Site abre na URL `.vercel.app` do projeto
- [ ] Ticker carrega PLD em tempo real (dados do JSON)
- [ ] Gráfico de PLD renderiza com Chart.js
- [ ] Termômetro do MWh com agulha animada
- [ ] 3 grids de notícias populados
- [ ] 4 calculadoras funcionando (migração, precificação, custo total, conta reversa)
- [ ] Newsletter envia e-mail de confirmação (testar com e-mail próprio)
- [ ] GoatCounter registrando pageviews
- [ ] GitHub Actions rodando sem erro
- [ ] Domínio `megagrid.com.br` aponta corretamente (após Passo 4)
- [ ] `www.megagrid.com.br` redireciona para `megagrid.com.br`
- [ ] SSL ativo (cadeado no navegador)

---

## Troubleshooting

**Newsletter retorna erro 500**
→ Confira `BREVO_API_KEY` e `BREVO_LIST_ID` nas variáveis de ambiente do Vercel.
→ No Vercel → Functions → Logs: veja o erro exato de `api/subscribe`.

**Robô falha na Action**
→ Veja o log em GitHub → Actions → execução falhada → expand o step "Executar fetch_data.py".
→ Se for erro de rede, é normal em endpoints instáveis — o seed JSON já garante dados mínimos.

**Dados do site não atualizam**
→ Confirme que o GitHub Actions fez commit em `site/data/`.
→ O Vercel só faz redeploy se houver push no repositório.
→ Verifique se a branch é `main` (não `master`).

**Domínio não propaga**
→ Teste em dnschecker.org.
→ TTL padrão do registro.br é 3600s (1h). Aguarde.

---

## Custos mensais estimados (escala inicial)

| Serviço | Custo |
|---|---|
| Vercel Hobby | R$ 0 |
| GitHub | R$ 0 |
| Brevo (até 300/dia) | R$ 0 |
| GoatCounter | R$ 0 |
| registro.br | R$ 3,33/mês (R$ 40/ano) |
| **Total** | **R$ 3,33/mês** |

> Para escalar: Vercel Pro (US$ 20/mês) quando precisar de mais bandwidth ou funções serverless robustas.
