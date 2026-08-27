#!/usr/bin/env python3
"""
MEGAGRID — Post automático no X (@megagridbr)

Roda no GitHub Actions, nas MESMAS execuções agendadas do robô de dados.
Compõe um post com os números do dia a partir dos JSONs que o fetch_data.py
acabou de gravar — nunca refaz busca: o post tem de dizer exatamente o que o
site está dizendo, e duas coletas separadas divergiriam.

REGRA DE CUSTO — NENHUMA URL NO TEXTO
A cobrança do X é por uso: post sem link custa US$ 0,015; post com QUALQUER
URL custa US$ 0,20 — treze vezes mais. E "URL" ali não é só link clicável:
texto puro como "megagrid.com.br" é auto-linkado pela plataforma e cobrado
como link. Por isso não há link no texto, não há link na assinatura, e existe
uma verificação por regex ANTES do envio que aborta o post se qualquer coisa
parecida com endereço aparecer. Um caractere errado aqui multiplica a conta
por treze, todo dia, para sempre.

REGRA DE PRECEDÊNCIA — O SITE É O PRODUTO, O POST É ACESSÓRIO
Nenhuma falha aqui pode derrubar o pipeline: rede, 401, 403, 429, resposta
ilegível, credencial ausente — tudo vira log e saída 0. O robô de dados
existia antes do X e tem de continuar existindo se o X sumir.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import check_freshness

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("post-x")

TZ_BR = ZoneInfo("America/Sao_Paulo")
DATA_DIR = Path(__file__).parent.parent / "site" / "data"
ESTADO = DATA_DIR / "last_post_x.json"

API_URL = "https://api.x.com/2/tweets"
LIMITE_CHARS = 280
JANELA_DUPLICATA_H = 20

# Hora UTC a partir da qual o run é "tarde". Os dois crons são 12:00 e 19:30
# UTC; 16h separa os dois com folga larga dos dois lados, então atraso de
# fila do Actions não troca o rótulo da edição.
UTC_CORTE_TARDE = 16

BANDEIRA_NOME = {
    "verde": "verde", "amarela": "amarela",
    "vermelha1": "vermelha P1", "vermelha2": "vermelha P2",
    "escassez": "escassez",
}

# Duas camadas: esquema/www explícito e qualquer coisa com cara de host.
# A segunda é deliberadamente ampla — nenhum texto legítimo desta composição
# tem ponto seguido de letra, então falso positivo aqui custa um post pulado,
# enquanto falso negativo custa 13x em dinheiro.
_RE_URL = re.compile(r"(?i)(?:\bhttps?://|\bwww\.|\b[\w-]+\.[a-z]{2,}\b)")


def _brl(v) -> str:
    """147.63 → '147,63'. Sempre 2 casas: '147,6' pareceria dado truncado."""
    return f"{float(v):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _carrega(nome: str) -> dict:
    try:
        return json.loads((DATA_DIR / nome).read_text("utf-8"))
    except Exception as exc:
        log.warning("  %s ilegível (%s) — post abortado", nome, exc)
        return {}


def compor(agora_utc: datetime = None) -> str:
    """Monta o texto. Levanta ValueError se faltar dado essencial — post com
    travessão no lugar do preço seria pior que post nenhum."""
    agora_utc = agora_utc or datetime.now(timezone.utc)
    edicao = "manhã" if agora_utc.hour < UTC_CORTE_TARDE else "tarde"
    data_br = agora_utc.astimezone(TZ_BR).strftime("%d/%m")

    pld = _carrega("pld.json")
    band = _carrega("bandeira.json")
    ear = _carrega("reservatorios.json")
    termo = _carrega("termometro.json")

    subs = pld.get("submercados") or {}
    # Submercado a submercado, SEMPRE — mesmo com os quatro valores iguais.
    # Aglutinar ("SE/CO, Sul e NE a 147,63") foi decidido contra no ticker:
    # some com a informação de que são preços independentes que por acaso
    # convergiram, que é justamente o que o leitor de mercado quer ver.
    faltando = [k for k in ("SE/CO", "S", "NE", "N")
                if (subs.get(k) or {}).get("preco") is None]
    if faltando:
        raise ValueError(f"PLD sem submercado(s): {', '.join(faltando)}")
    linha_pld = "PLD (R$/MWh): " + " · ".join(
        f"{rot} {_brl(subs[k]['preco'])}"
        for k, rot in (("SE/CO", "SE/CO"), ("S", "Sul"), ("NE", "NE"), ("N", "Norte")))

    cor = band.get("cor")
    comp = band.get("mes")
    if not cor or not comp:
        raise ValueError("bandeira sem cor ou competência")
    pct = ear.get("ear_percentual")
    if pct is None:
        raise ValueError("reservatórios sem ear_percentual")
    score = (termo or {}).get("score")

    cabecalho = f"⚡ Mercado agora — {data_br} · edição da {edicao}"
    # EAR com UMA casa, que é como a home e a página /reservatorios/ mostram.
    # Duas casas aqui e uma lá seria o mesmo número escrito de dois jeitos.
    linha_band = (f"Bandeira: {BANDEIRA_NOME.get(cor, cor)} ({comp}) · "
                  f"Reservatórios: {float(pct):.1f}".replace(".", ",") + "%")
    linha_termo = f"Termômetro do MWh: {score}/100" if score is not None else None

    def montar(band_txt, com_termo):
        partes = [cabecalho, "", linha_pld, band_txt]
        if com_termo and linha_termo:
            partes.append(linha_termo)
        return "\n".join(partes)

    # Degradação na ordem da spec: primeiro cai o termômetro (o dado mais
    # derivado), depois encurta o rótulo dos reservatórios. O PLD e a bandeira
    # nunca saem — são o motivo do post existir.
    for band_txt, com_termo, rotulo in (
        (linha_band, True, "completo"),
        (linha_band, False, "sem termômetro"),
        (linha_band.replace("Reservatórios:", "EAR:"), False, "sem termômetro + EAR"),
    ):
        texto = montar(band_txt, com_termo)
        if len(texto) <= LIMITE_CHARS:
            if rotulo != "completo":
                log.info("  texto degradado para caber em %d: %s", LIMITE_CHARS, rotulo)
            return texto
    raise ValueError(f"texto não coube em {LIMITE_CHARS} nem degradado")


def validar(texto: str):
    """Barreiras que rodam SEMPRE, inclusive em dry-run."""
    if len(texto) > LIMITE_CHARS:
        raise ValueError(f"texto com {len(texto)} chars (limite {LIMITE_CHARS})")
    achado = _RE_URL.search(texto)
    if achado:
        raise ValueError(f"texto contém algo com cara de URL ({achado.group(0)!r}) — "
                         f"custo subiria de US$ 0,015 para US$ 0,20 por post")
    if not texto.strip():
        raise ValueError("texto vazio")


def _hash_conteudo(texto: str) -> str:
    """Hash só do CORPO — a data e o rótulo da edição ficam de fora.

    É o que faz a anti-duplicata funcionar: dois runs no mesmo dia com os
    mesmos números têm corpos idênticos e hashes iguais, mesmo com
    cabeçalhos diferentes ('manhã' vs 'tarde')."""
    corpo = "\n".join(texto.split("\n")[1:]).strip()
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def duplicata(texto: str, agora_utc: datetime) -> bool:
    try:
        est = json.loads(ESTADO.read_text("utf-8"))
    except Exception:
        return False
    if est.get("hash") != _hash_conteudo(texto):
        return False
    try:
        quando = datetime.fromisoformat(str(est["postado_em"]).replace("Z", "+00:00"))
    except Exception:
        return False
    horas = (agora_utc - quando).total_seconds() / 3600
    if horas < JANELA_DUPLICATA_H:
        log.info("  conteúdo idêntico ao último post, feito há %.1fh "
                 "(janela de %dh) — pulando", horas, JANELA_DUPLICATA_H)
        return True
    log.info("  conteúdo idêntico, mas o último post foi há %.1fh — publicando", horas)
    return False


def grava_estado(texto: str, agora_utc: datetime):
    """Temporário + rename, mesma regra dos JSONs do robô: o arquivo é
    commitado logo depois e não pode ir pela metade."""
    payload = {
        "postado_em": agora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hash": _hash_conteudo(texto),
        "chars": len(texto),
        "texto": texto,
    }
    tmp = ESTADO.with_name(ESTADO.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, ESTADO)


def enviar(texto: str) -> bool:
    from requests_oauthlib import OAuth1Session
    faltando = [v for v in ("X_API_KEY", "X_API_SECRET",
                            "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
                if not os.environ.get(v)]
    if faltando:
        # Só os NOMES das variáveis ausentes; valor de chave não vai a log.
        log.warning("  credenciais ausentes: %s — não postado", ", ".join(faltando))
        return False
    sessao = OAuth1Session(
        os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])
    r = sessao.post(API_URL, json={"text": texto}, timeout=25)
    if r.status_code == 201:
        try:
            ident = r.json()["data"]["id"]
        except Exception:
            ident = "?"
        log.info("  publicado (id %s, %d chars)", ident, len(texto))
        return True
    # Corpo cru no log ajuda no 403 de permissão e no 429 de cota; nenhuma
    # credencial trafega na resposta.
    log.warning("  X respondeu HTTP %s: %s", r.status_code, r.text[:200])
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Publica o resumo do mercado no X.")
    ap.add_argument("--dry-run", action="store_true",
                    help="compõe e imprime o texto, sem enviar nem gravar estado")
    args = ap.parse_args()

    try:
        texto = compor()
        validar(texto)
    except Exception as exc:
        log.error("  composição falhou (%s: %s) — nada postado",
                  type(exc).__name__, exc)
        # Em dry-run o erro é do desenvolvedor e tem de ser barulhento; no
        # pipeline, ele não pode derrubar o run do robô.
        return 1 if args.dry_run else 0

    if args.dry_run:
        print("─" * 60)
        print(texto)
        print("─" * 60)
        print(f"{len(texto)} caracteres (limite {LIMITE_CHARS}) · "
              f"sem URL: {'sim' if not _RE_URL.search(texto) else 'NÃO'}")
        print(f"hash do corpo: {_hash_conteudo(texto)[:16]}")
        return 0

    try:
        falhas, _, _ = check_freshness.verificar()
        if falhas:
            log.warning("  dado estale, não postado — %d fonte(s) fora do limite: %s",
                        len(falhas), "; ".join(falhas)[:200])
            return 0

        agora = datetime.now(timezone.utc)
        if duplicata(texto, agora):
            return 0

        if os.environ.get("X_POST_ENABLED", "").strip().lower() != "true":
            log.info("  X_POST_ENABLED != true — post desligado, nada enviado")
            return 0

        if enviar(texto):
            grava_estado(texto, agora)
    except Exception as exc:
        log.warning("  post falhou (%s: %s) — o robô de dados segue normal",
                    type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
