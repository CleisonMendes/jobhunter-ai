"""
RADAR DE VAGAS — fonte_eureca.py (NOVO, independente)

Eureca: plataforma de estágios e programas de trainee.
  API:  GET https://candidate-api.eureca.me/opportunities?pageSize=8&page=N
  Cada vaga abre direto em: https://app.eureca.me/vagas/<id>/inscricao/formulario
  (a inscrição exige login e continua sendo feita por você)

Variáveis opcionais (mesmo estilo do fontes_extra.py):
  EURECA=0          desliga a fonte
  EURECA_FILTRO=0   traz TODAS as vagas. Por padrão só entram as que têm algum termo
                    de TERMOS_TITULO (do fontes_extra.py) ou TERMOS_EXTRA no título.
  EURECA_PAGINAS    máximo de páginas lidas (padrão 15; cada página tem 8 vagas)

Se a API falhar na 1ª página, levanta erro (o main.py conta como fonte quebrada,
igual ao Lever). Vagas com inscrição encerrada são ignoradas.

Teste isolado:  python fonte_eureca.py
"""

import html
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from fontes_extra import TERMOS_TITULO, _norm

API = "https://candidate-api.eureca.me/opportunities"
PAGE_SIZE = 8
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

EURECA_ATIVA   = os.environ.get("EURECA", "1") != "0"
EURECA_FILTRO  = os.environ.get("EURECA_FILTRO", "1") != "0"
EURECA_PAGINAS = int(os.environ.get("EURECA_PAGINAS", "15"))

# termos a mais, comuns em estágios de tecnologia/dados
TERMOS_EXTRA = ["tecnologia", "analytics", "inteligencia de mercado", "business intelligence"]


def _texto(h: str) -> str:
    h = re.sub(r"</(p|li|ul)>|<br\s*/?>", "\n", h or "")
    h = re.sub(r"<[^>]+>", "", h)
    h = html.unescape(h).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", h).strip()


def _data(valor):
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except Exception:
        return None


def _salario(s) -> str:
    if s and s.get("display") == "exact" and s.get("minCents"):
        return f"R$ {s['minCents'] / 100:,.0f}".replace(",", ".")
    return "não informado"


def _local(it: dict) -> str:
    modelo = (it.get("workModel") or "").lower()
    if modelo in ("remoto", "remote", "home_office"):
        return "Remoto"
    cidades = (it.get("locations") or {}).get("cities") or []
    # se a capital está entre as cidades da vaga, usa ela (o filtro de local prioriza SP)
    cidade = "São Paulo" if "São Paulo" in cidades else (it.get("cityName") or (cidades[0] if cidades else ""))
    uf = it.get("stateAcronym") or ""
    base = "/".join(x for x in (cidade, uf) if x) or "Brasil"
    return f"{base} ({modelo})" if modelo else base


def _normalizar(it: dict) -> dict:
    prazo = _data(it.get("endApplying"))
    prazo_txt = (prazo - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M") if prazo else "não informado"
    cabecalho = (
        f"Programa: {it.get('programName') or '—'}\n"
        f"Inscrições até: {prazo_txt} (horário de Brasília)\n"
        f"Bolsa/salário: {_salario(it.get('salary'))}\n"
        f"Carga: {it.get('weeklyHours') or '—'}h semanais\n\n"
    )
    return {
        "titulo":    it.get("name") or "—",
        "empresa":   it.get("companyName") or "—",
        "local":     _local(it),
        "fonte":     "Eureca",
        "link":      f"https://app.eureca.me/vagas/{it.get('id')}/inscricao/formulario",
        "data_pub":  None,   # a Eureca não informa publicação; o que vale é o prazo
        "descricao": cabecalho + _texto(it.get("description")),
    }


def buscar_todas_eureca(termos=None) -> list[dict]:
    termos = [_norm(t) for t in (termos or (TERMOS_TITULO + TERMOS_EXTRA))] if EURECA_FILTRO else []
    print("  📡 Buscando na Eureca...")
    agora = datetime.now(timezone.utc)
    vagas, vistos, lidas = [], set(), 0

    for pagina in range(1, EURECA_PAGINAS + 1):
        try:
            r = requests.get(API, params={"pageSize": PAGE_SIZE, "page": pagina},
                             headers=HEADERS, timeout=20)
            r.raise_for_status()
            dados = r.json()
        except Exception as e:
            if pagina == 1:
                raise RuntimeError(f"Eureca indisponível: {e}") from e   # fonte quebrada
            print(f"     ⚠️  Eureca página {pagina}: {e} (usando o que já foi lido)")
            break

        itens = dados.get("items") or []
        for it in itens:
            lidas += 1
            prazo = _data(it.get("endApplying"))
            if prazo and prazo < agora:
                continue
            v = _normalizar(it)
            if v["link"] in vistos:
                continue
            if termos and not any(t in _norm(v["titulo"]) for t in termos):
                continue
            vistos.add(v["link"])
            vagas.append(v)

        total = dados.get("total") or 0
        if not itens or pagina * PAGE_SIZE >= total:
            break
        time.sleep(0.5)

    print(f"     Eureca: {lidas} vaga(s) lida(s), {len(vagas)} aberta(s) e relevante(s)")
    return vagas


if __name__ == "__main__":
    resultado = buscar_todas_eureca()
    print(f"\n{len(resultado)} vaga(s) no resultado")
    for v in resultado[:5]:
        print(f"- {v['titulo']} | {v['empresa']} | {v['local']}\n  {v['link']}")
