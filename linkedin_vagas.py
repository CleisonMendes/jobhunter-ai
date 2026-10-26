"""Busca de VAGAS do LinkedIn pela lista pública (sem login).
Complementa o 'LinkedIn Posts'. Se o LinkedIn bloquear os servidores do GitHub
(HTTP 429/999), o log mostra o motivo e o robô segue com as outras fontes."""
import re
import time
import html
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

URL_BUSCA = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
URL_DETALHE = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}
# f_TPR=r604800 = publicadas nos últimos 7 dias | sortBy=DD = mais recentes primeiro
# geoId 106057199 = Brasil (fixa o país; só o texto "Brasil" deixava passar vagas de fora)
PARAMS_BASE = {"location": "Brazil", "geoId": "106057199", "f_TPR": "r604800", "sortBy": "DD"}


def _id_da_vaga(link: str) -> str:
    m = re.search(r"(\d{8,})(?:\?|$|/)", link or "")
    return m.group(1) if m else ""


def buscar_vagas_linkedin(termo: str, max_vagas: int = 25) -> list[dict]:
    print(f"\n🔍 [LinkedIn Vagas] Buscando: '{termo}'...")
    params = dict(PARAMS_BASE, keywords=termo, start=0)
    try:
        r = requests.get(URL_BUSCA, params=params, headers=HEADERS, timeout=20)
    except Exception as e:
        print(f"   ⚠️  LinkedIn Vagas: {type(e).__name__}: {str(e)[:100]}")
        return []
    if r.status_code != 200:
        print(f"   ⚠️  LinkedIn Vagas: HTTP {r.status_code} (provável bloqueio dos servidores)")
        return []

    soup = BeautifulSoup(r.text, "lxml")
    vagas = []
    for card in soup.select("li"):
        a = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        t = card.select_one(".base-search-card__title")
        if not a or not t:
            continue
        link = (a.get("href") or "").split("?")[0]
        if not link:
            continue
        empresa = card.select_one(".base-search-card__subtitle")
        local = card.select_one(".job-search-card__location")
        data = card.select_one("time")
        dt_txt = (data.get("datetime") if data else "") or ""
        try:
            dt = datetime.strptime(dt_txt[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
        vagas.append({
            "titulo":  html.unescape(t.get_text(" ", strip=True)),
            "empresa": empresa.get_text(" ", strip=True) if empresa else "",
            "local":   local.get_text(" ", strip=True) if local else "Brasil",
            "fonte":   "LinkedIn",
            "link":    link,
            "data_publicacao": dt_txt,
            "data_pub": dt,
        })
        if len(vagas) >= max_vagas:
            break
    time.sleep(1)  # educação com o servidor
    print(f"   ✅ {len(vagas)} vaga(s) encontrada(s)")
    return vagas


def descricao_linkedin(link: str) -> str:
    """Texto da vaga (para o Gemini analisar). Vazio se não conseguir."""
    vid = _id_da_vaga(link)
    if not vid:
        return ""
    r = requests.get(URL_DETALHE.format(id=vid), headers=HEADERS, timeout=15)
    if not r.ok:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    bloco = soup.select_one(".show-more-less-html__markup, .description__text")
    return bloco.get_text("\n", strip=True) if bloco else ""
