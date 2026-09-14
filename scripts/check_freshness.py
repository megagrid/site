#!/usr/bin/env python3
"""
MEGAGRID — Sentinela de frescor dos dados
Roda no GitHub Actions APÓS o commit do robô. Se alguma fonte estiver
parada além do limite, emite annotation ::error:: e sai com código 1 —
deixando o workflow VERMELHO (falha visível, em vez de erro silencioso).

Limites por arquivo (dias desde `updated`):
  noticias.json        2   (robô diário; Google News)
  mais-lidas.json      8   (semanal por cliques)
  termometro.json      2   (recalculado todo run)
  pld.json            10   (CCEE publica semanalmente)
  reservatorios.json   4   (ONS diário, com folga p/ atraso de publicação)
  carga.json           4   (ONS diário)
  bandeira.json       40   (ANEEL mensal)

Além do frescor do ARQUIVO, alguns dados têm COMPETÊNCIA própria e precisam
ser validados por ela (ver LIMITES_COMPETENCIA). E há um dado que não vem de
fonte nenhuma — o piso/teto do PLD é constante no código e envelhece sozinho,
uma vez por ano (ver verificar_limites_pld).
"""

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "site" / "data"

LIMITES_DIAS = {
    "noticias.json": 2,
    "mais-lidas.json": 8,
    "termometro.json": 2,
    "pld.json": 10,
    "reservatorios.json": 4,
    "carga.json": 4,
    "bandeira.json": 40,
}

# Sentinela por COMPETÊNCIA (P1.14). O limite acima só olha `updated`, isto é,
# quando o robô gravou o arquivo — e um arquivo gravado hoje com dado de seis
# anos atrás passa verde. Foi exatamente o que aconteceu em 17/08/2026: o
# extrator da bandeira passou a ler junho/2020, o arquivo estava fresco, o
# sentinela aprovou e a newsletter saiu com bandeira verde e adicional zero.
#
# Aqui a distância é medida entre o PRIMEIRO DIA do mês de competência e o
# primeiro dia do mês corrente. 40 dias tolera exatamente um mês de atraso
# (28–31d) — legítimo no começo do mês, antes de a ANEEL publicar o novo
# acionamento — e reprova dois meses (59d+) ou qualquer coisa mais velha.
LIMITES_COMPETENCIA = {
    "bandeira.json": 40,
}

_MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def idade_dias(iso: str) -> float:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def extrai_competencia(d: dict) -> tuple:
    """(ano, mes) do dado. Prefere o campo `competencia` (YYYY-MM); cai para o
    rótulo `mes` ("agosto/2026") nos arquivos gravados antes do P1.14."""
    comp = str(d.get("competencia") or "")
    m = re.match(r"^(\d{4})-(\d{2})", comp)
    if m:
        return int(m.group(1)), int(m.group(2))
    rotulo = str(d.get("mes") or "").strip().lower()
    m = re.match(r"^([^/]+)/(\d{4})$", rotulo)
    if m and m.group(1) in _MESES_PT:
        return int(m.group(2)), _MESES_PT.index(m.group(1)) + 1
    raise ValueError(f"competência não identificada (competencia={d.get('competencia')!r}, "
                     f"mes={d.get('mes')!r})")


def atraso_competencia_dias(ano: int, mes: int) -> int:
    hoje = date.today()
    return (date(hoje.year, hoje.month, 1) - date(ano, mes, 1)).days


# Guarda anual dos limites do PLD (14/09/2026). Piso e teto são homologados
# pela ANEEL a cada ano e moram em fetch_data.py, onde viviam sob um comentário
# pedindo "revisar anualmente" — que passou 2026 inteiro sem ser lido. Em
# 14/09/2026 o Norte apareceu no site a R$ 726,00, o teto de 2025, clampando um
# CMO de R$ 1.444 que o teto vigente (785,27) teria deixado em 785,27. Nenhum
# limite de frescor pegava isso: o arquivo estava fresco, a competência era da
# semana — só a régua é que era do ano passado. Comentário não alarma; sentinela
# alarma. Ano do run diferente do ano dos limites ⇒ run VERMELHO, igual a
# qualquer fonte parada, e o post no X fica bloqueado junto (post_x.py lê este
# mesmo julgamento).
def verificar_limites_pld() -> tuple:
    """(falha|None, linha). Lê as constantes do fetch_data — fonte única dos
    limites — em vez de manter aqui uma segunda cópia que um dia divergiria.
    Import adiado e protegido: este sentinela roda com `if: always()`, também
    quando o robô quebrou, e não pode morrer junto com ele."""
    try:
        from fetch_data import PLD_LIMITES_ANO, PLD_PISO, PLD_TETO
    except Exception as exc:
        msg = f"limites PLD ilegíveis em fetch_data.py ({type(exc).__name__}: {exc})"
        return msg, f"STALE  {msg}"

    ano_run = date.today().year
    st = (f"limites PLD: piso R$ {PLD_PISO:.2f} · teto R$ {PLD_TETO:.2f} "
          f"(homologados para {PLD_LIMITES_ANO}; run em {ano_run})")
    if PLD_LIMITES_ANO != ano_run:
        return (f"limites PLD desatualizados — revisar Despacho ANEEL do ano "
                f"(gravados para {PLD_LIMITES_ANO}, run em {ano_run})"), f"STALE  {st}"
    return None, f"ok     {st}"


def verificar() -> tuple:
    """(falhas, avisos, linhas). Separado do main() para que o post_x.py
    consulte o MESMO julgamento que deixa o run vermelho, em vez de manter
    uma segunda tabela de limites que um dia divergiria desta."""
    falhas, avisos, linhas = [], [], []
    for nome, limite in LIMITES_DIAS.items():
        p = DATA_DIR / nome
        try:
            doc = json.loads(p.read_text("utf-8"))
            idade = idade_dias(doc.get("updated"))
        except Exception as exc:
            falhas.append(f"{nome}: ilegível ({exc})")
            continue
        status = f"{nome}: {idade:.1f}d (limite {limite}d)"
        if idade > limite:
            falhas.append(status)
        elif idade > limite * 0.7:
            avisos.append(status)
        linhas.append(("STALE  " if idade > limite else "ok     ") + status)

        lim_comp = LIMITES_COMPETENCIA.get(nome)
        if lim_comp is None:
            continue
        try:
            ano, mes = extrai_competencia(doc)
        except ValueError as exc:
            falhas.append(f"{nome}: {exc}")
            linhas.append(f"STALE  {nome}: competência ilegível")
            continue
        atraso = atraso_competencia_dias(ano, mes)
        rotulo = f"{_MESES_PT[mes-1]}/{ano}"
        st = (f"{nome}: competência {rotulo} — {atraso}d atrás do mês corrente "
              f"(limite {lim_comp}d)")
        if atraso > lim_comp:
            falhas.append(st)
        elif atraso > lim_comp * 0.7:
            avisos.append(st)
        linhas.append(("STALE  " if atraso > lim_comp else "ok     ") + st)

    falha_pld, linha_pld = verificar_limites_pld()
    if falha_pld:
        falhas.append(falha_pld)
    linhas.append(linha_pld)

    return falhas, avisos, linhas


def main() -> int:
    falhas, avisos, linhas = verificar()
    for l in linhas:
        print(l)
    for a in avisos:
        print(f"::warning title=Fonte perto do limite::{a}")
    if falhas:
        for f in falhas:
            print(f"::error title=Fonte de dados PARADA::{f}")
        print(f"\n{len(falhas)} fonte(s) parada(s) — verifique o log do fetch acima.")
        return 1
    print("\nTodas as fontes dentro do limite de frescor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
