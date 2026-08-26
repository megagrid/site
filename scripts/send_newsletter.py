#!/usr/bin/env python3
"""
MEGAGRID — Robô da Newsletter Semanal
Lê os dados públicos (site/data/*.json), monta um e-mail branded Megagrid e
envia via API de campanhas do Brevo para a lista de inscritos.

Variáveis de ambiente (GitHub Actions Secrets):
  BREVO_API_KEY   → API key do Brevo (obrigatória)
  BREVO_LIST_ID   → ID da lista de inscritos (default: 4 = Megagrid Newsletter)
  DRY_RUN         → se "true", monta o HTML mas NÃO envia (para testes)

Uso:
  python scripts/send_newsletter.py
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")  # carimbo visível ao leitor

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "site", "data")
BREVO_API  = "https://api.brevo.com/v3"
SITE_URL   = "https://megagrid.com.br"
SENDER     = {"name": "Megagrid", "email": "contato@megagrid.com.br"}

# Paleta Megagrid
NAVY  = "#0A1426"
INK   = "#15212F"
MUT   = "#5B6B7E"
DIM   = "#8595A8"
LINE  = "#E3E8EF"
ALT   = "#F4F6F9"
BLUE  = "#1456D6"
UP    = "#D63B3B"   # preço subiu = ruim (vermelho)
DOWN  = "#1F9D61"   # preço caiu = bom (verde)
RIBBON = "linear-gradient(90deg,#00E0FF 0%,#2E6BFF 28%,#B43DFF 52%,#FF2E92 76%,#FF7A00 100%)"

EDITORIA_LABEL = {
    "mercado-livre": "Mercado Livre",
    "regulacao":     "Regulação",
    "politica":      "Política",
    "tarifas":       "Tarifas",
    "transicao":     "Transição",
}


def load(name, default=None):
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[newsletter] aviso: não li {name}: {exc}", file=sys.stderr)
        return default if default is not None else {}


def clean(text):
    text = (text or "").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # remove sufixo "  Fonte" duplicado
    return text


def num(v, casas=2):
    """Formata número no padrão PT-BR (vírgula decimal)."""
    try:
        return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)


def arrow(var):
    """Seta + cor para variação de preço (negativo = caiu = verde)."""
    if var is None:
        return "", MUT
    if var < 0:
        return f"▼ {num(abs(var), 1)}%", DOWN
    if var > 0:
        return f"▲ {num(var, 1)}%", UP
    return "0,0%", MUT


def br_date(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ_BR).strftime("%d/%m")
    except Exception:
        return ""


def build_html(pld, term, band, reserv, carga, noticias):
    hoje = datetime.now(TZ_BR)
    data_str = hoje.strftime("%d/%m/%Y")

    # --- Preços PLD por submercado ---
    sub = (pld or {}).get("submercados", {})
    nomes = {"SE/CO": "Sudeste/CO", "S": "Sul", "NE": "Nordeste", "N": "Norte"}
    linhas_pld = ""
    for cod in ["SE/CO", "S", "NE", "N"]:
        d = sub.get(cod)
        if not d:
            continue
        seta, cor = arrow(d.get("variacao"))
        linhas_pld += f"""
        <tr>
          <td style="padding:9px 0;border-bottom:1px solid {LINE};color:{INK};font-size:14px;">{nomes[cod]}</td>
          <td style="padding:9px 0;border-bottom:1px solid {LINE};color:{INK};font-size:14px;font-weight:700;text-align:right;">R$ {num(d.get('preco', 0))}</td>
          <td style="padding:9px 0 9px 14px;border-bottom:1px solid {LINE};color:{cor};font-size:13px;font-weight:700;text-align:right;white-space:nowrap;">{seta}</td>
        </tr>"""

    # --- Termômetro ---
    score = (term or {}).get("score", "—")
    nivel = (term or {}).get("nivel_desc", "")

    # --- Bandeira / Reservatórios / Carga ---
    band_cor = (band or {}).get("cor", "—").capitalize()
    ear = (reserv or {}).get("ear_percentual", "—")
    carga_mw = (carga or {}).get("carga_mwmed")
    carga_str = f"{num(carga_mw/1000, 1)} GWmed" if isinstance(carga_mw, (int, float)) else "—"

    # --- Top notícias da semana ---
    itens = (noticias or {}).get("itens", [])[:6]
    blocos_news = ""
    for it in itens:
        titulo = clean(it.get("titulo"))
        fonte  = it.get("fonte", "")
        ed     = EDITORIA_LABEL.get(it.get("editoria", ""), "")
        url    = it.get("url", SITE_URL)
        dt     = br_date(it.get("data", ""))
        meta   = " · ".join([x for x in [ed, fonte, dt] if x])
        blocos_news += f"""
        <tr><td style="padding:14px 0;border-bottom:1px solid {LINE};">
          <a href="{url}" style="color:{INK};text-decoration:none;font-size:15px;font-weight:700;line-height:1.4;">{titulo}</a>
          <div style="color:{DIM};font-size:12px;margin-top:5px;">{meta}</div>
        </td></tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{ALT};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="height:4px;background:{RIBBON};"></div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{ALT};">
<tr><td align="center" style="padding:0 12px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

    <!-- Header -->
    <tr><td style="padding:26px 8px 14px;">
      <span style="font-size:22px;font-weight:900;color:{NAVY};letter-spacing:.5px;">MEGAGRID</span>
      <span style="font-size:13px;color:{MUT};font-weight:600;margin-left:8px;">· Resumo da semana</span>
      <div style="color:{DIM};font-size:12px;margin-top:4px;">{data_str} — o essencial do mercado livre de energia, sem ruído.</div>
    </td></tr>

    <!-- Termômetro -->
    <tr><td style="padding:6px 8px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid {LINE};border-radius:14px;">
        <tr><td style="padding:18px 20px;">
          <div style="color:{BLUE};font-size:11px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;">Termômetro do MWh</div>
          <div style="margin-top:6px;"><span style="font-size:34px;font-weight:900;color:{NAVY};">{score}</span><span style="font-size:16px;color:{DIM};font-weight:700;">/100</span>
          <span style="font-size:14px;color:{MUT};margin-left:10px;">{nivel}</span></div>
        </td></tr>
      </table>
    </td></tr>

    <!-- Preços PLD -->
    <tr><td style="padding:12px 8px 6px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid {LINE};border-radius:14px;">
        <tr><td style="padding:18px 20px;">
          <div style="color:{BLUE};font-size:11px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px;">PLD por submercado (R$/MWh)</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{linhas_pld}</table>
          <div style="color:{DIM};font-size:11px;margin-top:10px;">Fonte: CCEE — Dados Abertos · variação vs. semana anterior</div>
        </td></tr>
      </table>
    </td></tr>

    <!-- Indicadores -->
    <tr><td style="padding:6px 8px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="33%" style="padding:4px;"><table role="presentation" width="100%" style="background:#fff;border:1px solid {LINE};border-radius:12px;"><tr><td style="padding:14px;text-align:center;"><div style="font-size:11px;color:{DIM};font-weight:700;">BANDEIRA</div><div style="font-size:16px;font-weight:800;color:{NAVY};margin-top:4px;">{band_cor}</div></td></tr></table></td>
          <td width="33%" style="padding:4px;"><table role="presentation" width="100%" style="background:#fff;border:1px solid {LINE};border-radius:12px;"><tr><td style="padding:14px;text-align:center;"><div style="font-size:11px;color:{DIM};font-weight:700;">RESERVATÓRIOS</div><div style="font-size:16px;font-weight:800;color:{NAVY};margin-top:4px;">{ear}%</div></td></tr></table></td>
          <td width="33%" style="padding:4px;"><table role="presentation" width="100%" style="background:#fff;border:1px solid {LINE};border-radius:12px;"><tr><td style="padding:14px;text-align:center;"><div style="font-size:11px;color:{DIM};font-weight:700;">CARGA SIN</div><div style="font-size:16px;font-weight:800;color:{NAVY};margin-top:4px;">{carga_str}</div></td></tr></table></td>
        </tr>
      </table>
    </td></tr>

    <!-- Notícias -->
    <tr><td style="padding:14px 8px 6px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid {LINE};border-radius:14px;">
        <tr><td style="padding:18px 20px;">
          <div style="color:{BLUE};font-size:11px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:4px;">Destaques da semana</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{blocos_news}</table>
        </td></tr>
      </table>
    </td></tr>

    <!-- CTA -->
    <tr><td align="center" style="padding:22px 8px 8px;">
      <a href="{SITE_URL}" style="display:inline-block;background:{BLUE};color:#fff;font-weight:700;font-size:15px;padding:13px 30px;border-radius:10px;text-decoration:none;">Ver tudo no Megagrid →</a>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:24px 8px;text-align:center;color:{DIM};font-size:12px;line-height:1.6;">
      Megagrid · O mercado livre de energia, traduzido em dados.<br>
      Conteúdo informativo baseado em dados públicos (CCEE, ONS, ANEEL, MME, EPE).<br>
      <a href="{{{{ unsubscribe }}}}" style="color:{DIM};text-decoration:underline;">Descadastrar</a>
    </td></tr>

  </table>
</td></tr>
</table>
</body></html>"""
    return html


def main():
    api_key = os.environ.get("BREVO_API_KEY")
    list_id = int((os.environ.get("BREVO_LIST_ID") or "4").strip() or "4")
    dry_run = os.environ.get("DRY_RUN", "").lower() == "true"

    pld      = load("pld.json")
    term     = load("termometro.json")
    band     = load("bandeira.json")
    reserv   = load("reservatorios.json")
    carga    = load("carga.json")
    noticias = load("noticias.json")

    # Segurança: não enviar e-mail quebrado se faltam dados essenciais
    if not pld.get("submercados") or not noticias.get("itens"):
        print("[newsletter] ERRO: dados essenciais (PLD/notícias) ausentes — abortando envio.", file=sys.stderr)
        sys.exit(1)

    html = build_html(pld, term, band, reserv, carga, noticias)

    hoje = datetime.now(TZ_BR).strftime("%d/%m")
    subject = f"Megagrid · Resumo da semana — {hoje}"
    name    = f"Newsletter Semanal Megagrid — {hoje}"

    if dry_run or not api_key:
        out = os.path.join(os.path.dirname(__file__), "..", "newsletter_preview.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[newsletter] DRY_RUN/sem API key — HTML salvo em {out} (nenhum envio).")
        return

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key,
        # UA explícito: o default "Python-urllib" sofre bloqueio intermitente
        # em CDNs — causa provável das falhas de 22/06 e 13/07.
        "user-agent": "Megagrid-Newsletter/1.1 (+https://megagrid.com.br)",
    }

    def brevo_post(url, payload=None, tentativas=3, timeout=30):
        """POST com timeout explícito e retry/backoff (Brevo pode dar 5xx/timeout transitório)."""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        ultimo = ""
        for i in range(1, tentativas + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    corpo = resp.read().decode("utf-8", "ignore")
                    return resp.status, (json.loads(corpo) if corpo.strip() else {})
            except urllib.error.HTTPError as e:
                corpo = e.read().decode("utf-8", "ignore")[:300]
                ultimo = f"HTTP {e.code}: {corpo}"
                # 4xx (exceto 429) não adianta repetir
                if e.code < 500 and e.code != 429:
                    break
            except Exception as e:
                ultimo = f"{type(e).__name__}: {e}"
            print(f"[newsletter] tentativa {i}/{tentativas} falhou → {ultimo}", file=sys.stderr)
            if i < tentativas:
                time.sleep(5 * i)
        print(f"[newsletter] ERRO em {url} → {ultimo}", file=sys.stderr)
        sys.exit(1)

    # 1) Criar campanha
    _, body = brevo_post(f"{BREVO_API}/emailCampaigns", {
        "name": name,
        "subject": subject,
        "sender": SENDER,
        "type": "classic",
        "htmlContent": html,
        "recipients": {"listIds": [list_id]},
    })
    campaign_id = body.get("id")
    print(f"[newsletter] Campanha criada: id={campaign_id}")

    # 2) Enviar agora
    status, _ = brevo_post(f"{BREVO_API}/emailCampaigns/{campaign_id}/sendNow")
    print(f"[newsletter] Envio disparado (status {status}). Assunto: {subject}")


if __name__ == "__main__":
    main()
