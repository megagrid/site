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
# Endpoint de identidade: a chamada mais barata que prova que a credencial
# vale. Não escreve nada, devolve o handle — serve ao mesmo tempo de teste de
# autenticação e de confirmação de que as chaves são da conta certa.
API_ME_URL = "https://api.x.com/2/users/me"
LIMITE_CHARS = 280
JANELA_DUPLICATA_H = 20

# A ordem é a ordem POSICIONAL do OAuth1Session (client key, client secret,
# resource owner key, resource owner secret). Trocar duas aqui dá 401.
CREDENCIAIS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")

# Estes dois textos vão para o heartbeat, que é público. Dizem o que FAZER,
# não só o que houve: quem lê o arquivo às 3h da manhã não quer um código HTTP,
# quer a próxima ação.
MOTIVO_401 = "credencial rejeitada (401) — regenerar chaves e recolar secrets"
MOTIVO_403 = "app sem permissão de escrita (403) — conferir Read and Write no portal"

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


def _fingerprints() -> dict:
    """SHA-256 truncado (8 hex) de cada credencial — NUNCA o valor.

    Responde de fora uma pergunta que antes exigia adivinhação: "a chave que
    recolei hoje chegou ao runner?". O fingerprint muda quando o secret muda,
    então comparar dois heartbeats basta. Publicar 32 bits de um SHA-256 de
    segredo de alta entropia não é vazamento: não se volta ao valor a partir
    disso, e quem já tivesse o valor não precisaria do fingerprint.

    O hash é do valor CRU, sem strip(): secret colado com espaço ou quebra de
    linha no fim é causa clássica de 401, e normalizar aqui esconderia
    exatamente o defeito que este campo existe para revelar — por isso o
    espaço nas pontas é ANOTADO em vez de removido.
    """
    fps = {}
    for var in CREDENCIAIS:
        bruto = os.environ.get(var)
        if not bruto:
            fps[var] = "ausente"
            continue
        fp = hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:8]
        fps[var] = (fp + " (espaço nas pontas)") if bruto != bruto.strip() else fp
    return fps


def _sessao() -> tuple:
    """(sessao, faltando). UMA construção de credencial para o --check e para o
    envio: duas cópias divergiriam no dia em que uma variável mudasse de nome,
    e o --check passaria a testar algo que o envio não usa."""
    from requests_oauthlib import OAuth1Session
    faltando = [v for v in CREDENCIAIS if not os.environ.get(v)]
    if faltando:
        return None, faltando
    return OAuth1Session(*(os.environ[v] for v in CREDENCIAIS)), []


def verificar_credencial() -> tuple:
    """(codigo, motivo). codigo ∈ {ok, ausente, 401, 403, indefinido}.

    GET /2/users/me com as MESMAS credenciais do envio. Custa uma leitura por
    run que posta e responde em segundos o que antes levava dias: a chave foi
    rejeitada, o app perdeu a escrita, ou o problema é outro?

    'indefinido' é deliberado e é o coração da regra de precedência: 429, 5xx,
    DNS caído — nada disso pode SUPRIMIR um post que talvez funcionasse. Só 401
    e 403 abortam, porque são exatamente os casos em que o envio repetiria a
    mesma resposta. Um diagnóstico que derruba o que veio diagnosticar é pior
    que diagnóstico nenhum.
    """
    sessao, faltando = _sessao()
    if faltando:
        return "ausente", "credenciais ausentes: " + ", ".join(faltando)
    try:
        r = sessao.get(API_ME_URL, timeout=15)
    except Exception as exc:
        return "indefinido", f"{type(exc).__name__}: {exc}"
    if r.status_code == 200:
        try:
            return "ok", "@" + r.json()["data"]["username"]
        except Exception:
            return "ok", "handle ilegível na resposta"
    if r.status_code == 401:
        return "401", MOTIVO_401
    if r.status_code == 403:
        return "403", MOTIVO_403
    return "indefinido", f"HTTP {r.status_code}: {r.text[:180]}"


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


def _le_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text("utf-8"))
    except Exception:
        return {}


def duplicata(texto: str, agora_utc: datetime) -> bool:
    est = _le_estado()
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


def _payload_estado(agora_utc: datetime, status: str, motivo: str = "",
                    texto: str = None) -> dict:
    """Monta o dicionário do heartbeat. Existe separado da gravação para que o
    --dry-run possa MOSTRAR o arquivo que sairia sem escrever nada — um
    segundo trecho montando a mesma forma acabaria divergindo dela."""
    payload = {
        "verificado_em": agora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "motivo": motivo,
        "fingerprints": _fingerprints(),
    }
    if texto is not None:
        payload.update({
            "postado_em": agora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hash": _hash_conteudo(texto),
            "chars": len(texto),
            "texto": texto,
        })
    else:
        anterior = _le_estado()
        for campo in ("postado_em", "hash", "chars", "texto"):
            if campo in anterior:
                payload[campo] = anterior[campo]
    return payload


def grava_estado(agora_utc: datetime, status: str, motivo: str = "",
                 texto: str = None):
    """Estado do post — gravado em TODA execução, não só quando há post.

    DUAS COISAS NO MESMO ARQUIVO, e a distinção é o ponto:

      · HEARTBEAT (verificado_em/status/motivo) — reescrito a cada run.
        Sem ele não há como diferenciar "o post foi corretamente pulado"
        de "o passo nunca rodou": os dois davam 404 em /data/last_post_x.json
        e o módulo saía 0 nos dois casos. O `status` diz qual camada barrou,
        então o diagnóstico não depende mais de ler o log do Actions — que
        exige direito de admin no repositório.

      · MEMÓRIA DO ÚLTIMO POST (postado_em/hash/chars/texto) — só é
        reescrita quando o X aceitou o post. Um skip PRESERVA os campos
        anteriores. Carimbá-los no skip envenenaria a anti-duplicata:
        duplicata() passaria a comparar com um texto que nunca foi ao ar e
        o post do dia seguinte seria suprimido por um post que não existiu.

      · FINGERPRINTS — reescritos a cada run, junto do heartbeat. São a
        resposta a "a chave que recolei chegou ao runner?", que antes não
        tinha resposta nenhuma de fora do Actions. Ver _fingerprints().

    Temporário + rename, mesma regra dos JSONs do robô: o arquivo é
    commitado logo depois e não pode ir pela metade."""
    payload = _payload_estado(agora_utc, status, motivo, texto)
    tmp = ESTADO.with_name(ESTADO.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, ESTADO)


def _heartbeat(agora_utc: datetime, status: str, motivo: str = "",
               texto: str = None):
    """A gravação do heartbeat não pode ser o que derruba o post (regra de
    precedência do cabeçalho): disco cheio ou permissão ruim vira log."""
    try:
        grava_estado(agora_utc, status, motivo, texto)
    except Exception as exc:
        log.warning("  não consegui gravar %s (%s: %s)",
                    ESTADO.name, type(exc).__name__, exc)


def enviar(texto: str) -> tuple:
    """(ok, motivo). O motivo vai para o heartbeat: é ele que separa
    credencial ausente de 403 de token revogado e de 429 de cota estourada
    sem precisar do log do Actions. Nenhum VALOR de credencial entra no
    motivo — só nomes de variável e o que o X respondeu."""
    sessao, faltando = _sessao()
    if faltando:
        # Só os NOMES das variáveis ausentes; valor de chave não vai a log.
        log.warning("  credenciais ausentes: %s — não postado", ", ".join(faltando))
        return False, "credenciais ausentes: " + ", ".join(faltando)
    r = sessao.post(API_URL, json={"text": texto}, timeout=25)
    if r.status_code == 201:
        try:
            ident = r.json()["data"]["id"]
        except Exception:
            ident = "?"
        log.info("  publicado (id %s, %d chars)", ident, len(texto))
        return True, f"id {ident}"
    # Corpo cru no log ajuda no 403 de permissão e no 429 de cota; nenhuma
    # credencial trafega na resposta.
    log.warning("  X respondeu HTTP %s: %s", r.status_code, r.text[:200])
    return False, f"HTTP {r.status_code}: {r.text[:180]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Publica o resumo do mercado no X.")
    ap.add_argument("--dry-run", action="store_true",
                    help="compõe e imprime o texto, sem enviar nem gravar estado")
    ap.add_argument("--check", action="store_true",
                    help="testa a credencial em /2/users/me e sai; não compõe nem envia")
    args = ap.parse_args()

    agora = datetime.now(timezone.utc)

    # --check vem antes de tudo: não depende de dado no disco, e o ponto dele é
    # justamente responder quando o resto está quebrado. Sai 1 em falha porque
    # é modo de diagnóstico local, nunca roda no workflow — a regra de saída 0
    # protege o pipeline, e aqui não há pipeline para proteger.
    if args.check:
        codigo, motivo = verificar_credencial()
        print(f"credencial ok: {motivo}" if codigo == "ok"
              else f"credencial NÃO ok [{codigo}]: {motivo}")
        print("fingerprints (SHA-256, 8 hex — nunca o valor):")
        for var, fp in _fingerprints().items():
            print(f"  {var:16s} {fp}")
        return 0 if codigo == "ok" else 1
    try:
        texto = compor(agora)
        validar(texto)
    except Exception as exc:
        log.error("  composição falhou (%s: %s) — nada postado",
                  type(exc).__name__, exc)
        # Em dry-run o erro é do desenvolvedor e tem de ser barulhento; no
        # pipeline, ele não pode derrubar o run do robô.
        if args.dry_run:
            return 1
        _heartbeat(agora, "erro-composicao", f"{type(exc).__name__}: {exc}")
        return 0

    if args.dry_run:
        print("─" * 60)
        print(texto)
        print("─" * 60)
        print(f"{len(texto)} caracteres (limite {LIMITE_CHARS}) · "
              f"sem URL: {'sim' if not _RE_URL.search(texto) else 'NÃO'}")
        print(f"hash do corpo: {_hash_conteudo(texto)[:16]}")
        # Mostra o ARQUIVO que sairia, fingerprints inclusive, sem gravá-lo:
        # o formato do heartbeat é conferível localmente antes de ir ao ar.
        print("\nheartbeat que seria gravado (dry-run NÃO grava):")
        print(json.dumps(_payload_estado(agora, "publicado", "(simulado)", texto),
                         ensure_ascii=False, indent=2))
        return 0

    # Cada saída daqui para baixo grava o heartbeat com a camada que barrou.
    # "Pulado" e "nunca rodou" precisam ser distinguíveis de fora do Actions:
    # antes os dois davam 404 em /data/last_post_x.json.
    try:
        falhas, _, _ = check_freshness.verificar()
        if falhas:
            log.warning("  dado estale, não postado — %d fonte(s) fora do limite: %s",
                        len(falhas), "; ".join(falhas)[:200])
            _heartbeat(agora, "pulado-dado-estale", "; ".join(falhas)[:200])
            return 0

        if duplicata(texto, agora):
            _heartbeat(agora, "pulado-duplicata",
                       f"corpo idêntico ao último post, dentro da janela de "
                       f"{JANELA_DUPLICATA_H}h")
            return 0

        if os.environ.get("X_POST_ENABLED", "").strip().lower() != "true":
            log.info("  X_POST_ENABLED != true — post desligado, nada enviado")
            _heartbeat(agora, "pulado-desligado", "X_POST_ENABLED != true")
            return 0

        # ÚLTIMA porta antes do envio, e de propósito: posta depois dos gates
        # de frescor/duplicata/desligado para não gastar uma leitura da API nos
        # runs que já se sabe que não vão postar. Os fingerprints, esses, vão
        # ao heartbeat em TODA execução — inclusive nas puladas.
        codigo, motivo_cred = verificar_credencial()
        if codigo in ("401", "403", "ausente"):
            log.warning("  %s — não postado", motivo_cred)
            _heartbeat(agora, "falha-credencial", motivo_cred)
            return 0
        if codigo == "indefinido":
            # Não sabemos se a credencial presta; tentar o post é melhor que
            # suprimi-lo por causa de um 429 na verificação.
            log.info("  verificação inconclusiva (%s) — seguindo para o envio",
                     motivo_cred)
        else:
            log.info("  credencial ok: %s", motivo_cred)

        ok, motivo = enviar(texto)
        _heartbeat(agora, "publicado" if ok else "falha-envio", motivo,
                   texto=texto if ok else None)
    except Exception as exc:
        log.warning("  post falhou (%s: %s) — o robô de dados segue normal",
                    type(exc).__name__, exc)
        _heartbeat(agora, "erro", f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
