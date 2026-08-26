#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  MEGAGRID — Script de setup inicial do repositório GitHub
#  Uso: bash scripts/deploy-setup.sh [ORG_OU_USUARIO]
#  Sem argumento, usa a org "megagrid" (github.com/megagrid/site).
# ═══════════════════════════════════════════════════════════
set -e

# Org dona do repositório. O projeto migrou de conta pessoal para a
# org "megagrid" em 24/08/2026 — o repo lá se chama "site", não
# "megagrid-site", porque o nome da org já diz o produto.
GITHUB_USER=${1:-"megagrid"}
REPO_NAME="site"

# Vai para a raiz do projeto (pasta pai de /scripts)
cd "$(dirname "$0")/.."

echo ""
echo "🔧 Inicializando repositório Git..."
git init
git add .
git commit -m "feat: Megagrid v1 — site dinâmico com robô de dados e 4 calculadoras"
git branch -M main

echo ""
echo "🔗 Conectando ao repositório remoto..."
git remote add origin "https://github.com/$GITHUB_USER/$REPO_NAME.git" 2>/dev/null || \
  git remote set-url origin "https://github.com/$GITHUB_USER/$REPO_NAME.git"

echo ""
echo "📤 Enviando para GitHub..."
git push -u origin main

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅ Código no ar: github.com/$GITHUB_USER/$REPO_NAME"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Próximos passos (ver DEPLOY.md):                   ║"
echo "║  1. Vercel → Add New → Import Git Repository        ║"
echo "║  2. Output Directory: site                          ║"
echo "║  3. Adicionar variáveis de ambiente (Brevo, etc.)   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
