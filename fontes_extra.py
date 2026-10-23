"""
RADAR DE VAGAS — fontes_extra.py (NOVO)

Lever: API pública, com data de publicação e descrição completa.
  GET https://api.lever.co/v0/postings/<empresa>?mode=json
  (empresas na Europa usam api.eu.lever.co: ajuste LEVER_HOST se for o caso)

Configure as empresas com o segredo/variável LEVER_EMPRESAS (separadas por vírgula).
O nome da empresa é o trecho final do endereço da página de vagas dela:
  jobs.lever.co/nome-da-empresa  →  nome-da-empresa
Sem LEVER_EMPRESAS, a fonte fica desligada.

ProgramaThor: página pública de listagem (sem API), lida pelo HTML.
  Cidades: PROGRAMATHOR_CIDADES (padrão "sao-paulo,remoto")
  Níveis:  PROGRAMATHOR_NIVEIS  (padrão "Júnior,Pleno")
  Páginas: PROGRAMATHOR_PAGINAS (padrão 2 por cidade/nível)
  Desligar: PROGRAMATHOR=0
Vagas marcadas como "Vencida" no site são ignoradas.
"""

import os
import re
import time
import html
import unicodedata
import requests
from urllib.parse import quote
from datetime import datetime, timezone

LEVER_HOST = os.environ.get("LEVER_HOST", "api.lever.co")
LEVER_EMPRESAS = [s.strip() for s in os.environ.get("LEVER_EMPRESAS", "").split(",") if s.strip()]

# mesmos termos do pré-filtro do main.py (só entram vagas com algum desses no título)
TERMOS_TITULO = [
    "antifraude", "chargeback", "fraude", "risco", "dados", "data", "python", "sql", "backoffice",
    "desenvolvedor", "desenvolvedora", "developer", "full stack", "fullstack", "full-stack",
    "javascript", "react", "node", "qa", "teste", "automacao", "rpa", "sistemas",
    "suporte tecnico", "integracao",
    "programador", "software", "backend", "back-end", "back end",
    "frontend", "front-end", "front end", "typescript", "java", "php",
]


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFD", (txt or "").lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def _data(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except Exception:
        return None


def buscar_vagas_lever(slug: str, termos=None) -> list[dict]:
    termos = [_norm(t) for t in (termos or TERMOS_TITULO)]
    url = f"https://{LEVER_HOST}/v0/postings/{slug}"
    try:
        resp = requests.get(url, params={"mode": "json"}, timeout=20,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        itens = resp.json()
    except Exception as e:
        print(f"   ⚠️  Erro Lever ({slug}): {e}")
        raise  # quem chama conta como erro da fonte

    vagas = []
    for p in itens if isinstance(itens, list) else []:
        titulo = p.get("text", "")
        if termos and not any(t in _norm(titulo) for t in termos):
            continue
        cat = p.get("categories") or {}
        local = "Remoto" if p.get("workplaceType") == "remote" else (cat.get("location") or "Brasil")
        descricao = "\n".join(filter(None, [p.get("descriptionPlain"), p.get("additionalPlain")]))
        vagas.append({
            "titulo":  titulo,
            "empresa": slug.replace("-", " ").title(),
            "local":   local,
            "fonte":   "Lever",
            "link":    p.get("hostedUrl", ""),
            "data_pub": _data(p.get("createdAt")),
            "descricao": descricao,
        })
    return vagas


def buscar_todas_lever(termos=None) -> list[dict]:
    """Todas as empresas de LEVER_EMPRESAS. Se TODAS falharem, levanta erro (a fonte está quebrada)."""
    print("  📡 Buscando no Lever...")
    todas, erros = [], 0
    for slug in LEVER_EMPRESAS:
        try:
            achadas = buscar_vagas_lever(slug, termos)
            print(f"     {slug}: {len(achadas)} vaga(s) relevante(s)")
            todas.extend(achadas)
        except Exception:
            erros += 1
    if LEVER_EMPRESAS and erros == len(LEVER_EMPRESAS):
        raise RuntimeError("todas as empresas do Lever falharam")
    return todas


# ====================================================================
# ── PROGRAMATHOR ─────────────────────────────────────────────────────
# ====================================================================

PROGRAMATHOR_ATIVO   = os.environ.get("PROGRAMATHOR", "1") != "0"
PROGRAMATHOR_CIDADES = [c.strip() for c in os.environ.get("PROGRAMATHOR_CIDADES", "sao-paulo,remoto").split(",") if c.strip()]
PROGRAMATHOR_NIVEIS  = [n.strip() for n in os.environ.get("PROGRAMATHOR_NIVEIS", "Júnior,Pleno").split(",") if n.strip()]
PROGRAMATHOR_PAGINAS = int(os.environ.get("PROGRAMATHOR_PAGINAS", "2"))

_PT_BASE = "https://programathor.com.br"
_PT_CARD = re.compile(r'<a\b[^>]*href="(?:https://programathor\.com\.br)?(/jobs/(\d+)-([^"#?]*))(?:[?#][^"]*)?"[^>]*>(.*?)</a>',
                      re.S | re.I)
_PT_LOCAL = re.compile(r"\((H[ií]brido|Presencial|Remoto)\)|^Remoto$", re.I)


def _linhas_do_card(inner_html: str) -> list[str]:
    t = re.sub(r"<[^>]+>", "\n", inner_html)
    t = html.unescape(t).replace("\xa0", " ")
    return [l.strip() for l in t.split("\n") if l.strip()]


def _titulo_do_slug(slug: str) -> str:
    t = re.sub(r"-+", " ", slug).strip()
    return t[:1].upper() + t[1:]


def _parse_programathor(htm: str) -> list[dict]:
    """Lê os cards da listagem. Título/empresa vêm do texto do card; se não baterem com o
    endereço da vaga (slug), usa o título do slug. Vagas 'Vencida' são ignoradas."""
    vagas, vistos = [], set()
    for m in _PT_CARD.finditer(htm):
        caminho, vid, slug, inner = m.groups()
        if vid in vistos:
            continue
        vistos.add(vid)
        linhas = _linhas_do_card(inner)
        if not linhas:
            continue
        if re.search(r"\bVencida\b", " ".join(linhas)):
            continue

        idx_local = next((i for i, l in enumerate(linhas) if _PT_LOCAL.search(l)), None)
        local, empresa, titulo = "", "", ""
        if idx_local is not None:
            local = linhas[idx_local]
            if idx_local >= 1:
                empresa = linhas[idx_local - 1]
            if idx_local >= 2:
                titulo = linhas[idx_local - 2]
        titulo = re.sub(r"\s+NOVA$", "", titulo).strip()   # selo "NOVA" do site
        palavras_slug = {w for w in _norm(slug).split("-") if len(w) > 2}
        if not titulo or not (palavras_slug & set(re.findall(r"\w{3,}", _norm(titulo)))):
            titulo = _titulo_do_slug(slug)

        remoto = "remoto" in _norm(local)
        vagas.append({
            "titulo":  titulo,
            "empresa": empresa or "ProgramaThor",
            "local":   "Remoto" if remoto else (re.sub(r"\s+", " ", local) or "São Paulo"),
            "fonte":   "ProgramaThor",
            "link":    f"{_PT_BASE}{caminho}",
        })
    return vagas


def buscar_todas_programathor() -> list[dict]:
    """Cidades x níveis x páginas. Se TODAS as requisições falharem, levanta erro (fonte quebrada).
    Se carregar mas vier 0 vaga, devolve [] (o alerta de fonte avisa após algumas rodadas)."""
    print("  📡 Buscando no ProgramaThor...")
    todas, vistos, ok, falhas = [], set(), 0, 0
    for cidade in PROGRAMATHOR_CIDADES:
        for nivel in (PROGRAMATHOR_NIVEIS or [""]):
            for pagina in range(1, PROGRAMATHOR_PAGINAS + 1):
                url = f"{_PT_BASE}/jobs-city/{cidade}?page={pagina}"
                if nivel:
                    url += f"&expertise={quote(nivel)}"
                try:
                    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                    r.raise_for_status()
                    ok += 1
                    novas = [v for v in _parse_programathor(r.text) if v["link"] not in vistos]
                    vistos.update(v["link"] for v in novas)
                    todas.extend(novas)
                    print(f"     {cidade}/{nivel or 'todos'}/pág {pagina}: {len(novas)} vaga(s) aberta(s)")
                    if not novas:
                        break  # acabou a lista
                except Exception as e:
                    falhas += 1
                    print(f"     ⚠️  ProgramaThor {cidade}/{nivel}/pág {pagina}: {e}")
                    break
                time.sleep(1)  # leve com o site
    if ok == 0 and falhas:
        raise RuntimeError("todas as requisições ao ProgramaThor falharam")
    return todas
