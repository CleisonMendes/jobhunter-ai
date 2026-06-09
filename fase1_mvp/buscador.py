"""
==============================================
  JOBHUNTER AI — Fase 1: Buscador de Vagas
  Bloco 3+: Captura de data de publicação
==============================================
Fontes suportadas:
  - Gupy        (API pública — tem data)
  - Greenhouse  (API pública — sem data)
  - Indeed      (scraping — sem data confiável)
  - LinkedIn    (RSS — tem pubDate)
  - LinkedIn    (Posts via DuckDuckGo — sem data)
"""

import requests
import urllib.parse
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

EMPRESAS_GREENHOUSE = {
    "Nubank":   "nubank",
    "Stone":    "stone",
    "XP Inc.":  "xpinc",
    "Pagar.me": "pagarme",
    "Creditas": "creditas",
    "Dock":     "dock",
    "Quanto":   "quanto",
}


# ── UTILITÁRIO: parse de data ─────────────────────────────────────────────────

def _parse_data(texto: str | None) -> datetime | None:
    """
    Tenta converter uma string de data para datetime com timezone UTC.
    Aceita formatos ISO 8601 e RFC 2822 (usado no RSS).
    Retorna None se não conseguir parsear.
    """
    if not texto:
        return None
    formatos = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",   # RFC 2822 — usado no RSS
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in formatos:
        try:
            dt = datetime.strptime(texto.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ── FONTE 1: Gupy ─────────────────────────────────────────────────────────────

def buscar_vagas_gupy(cargo: str) -> list[dict]:
    vagas_encontradas = []
    url = "https://portal.api.gupy.io/api/v1/jobs"
    parametros = {"jobName": cargo, "limit": 20, "offset": 0}

    try:
        print(f"\n🔍 [Gupy] Buscando: '{cargo}'...")
        resposta = requests.get(url, params=parametros, headers=HEADERS, timeout=10)
        resposta.raise_for_status()

        for vaga in resposta.json().get("data", []):
            titulo  = vaga.get("name", "Sem título")
            empresa = vaga.get("company", {}).get("name", "Empresa não informada")
            link    = vaga.get("jobUrl", "")
            cidade  = vaga.get("city", "")
            estado  = vaga.get("state", "")
            local   = f"{cidade}/{estado}" if cidade else "Remoto / Não informado"

            # ── DATA: Gupy retorna publishedDate no JSON ──────────────
            data_pub = _parse_data(vaga.get("publishedDate") or vaga.get("createdAt"))

            vagas_encontradas.append({
                "titulo":       titulo,
                "empresa":      empresa,
                "local":        local,
                "link":         link,
                "fonte":        "Gupy",
                "data_pub":     data_pub,
            })

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except requests.exceptions.Timeout:
        print("   ⚠️  Timeout — Gupy demorou para responder.")
    except requests.exceptions.HTTPError as e:
        print(f"   ⚠️  Erro HTTP Gupy: {e}")
    except Exception as e:
        print(f"   ⚠️  Erro inesperado Gupy: {e}")

    return vagas_encontradas


# ── FONTE 2: Greenhouse ───────────────────────────────────────────────────────

def buscar_vagas_greenhouse(empresa_nome: str, empresa_slug: str) -> list[dict]:
    vagas_encontradas = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{empresa_slug}/jobs"

    try:
        print(f"\n🔍 [Greenhouse] Buscando vagas em: {empresa_nome}...")
        resposta = requests.get(url, headers=HEADERS, timeout=10)
        resposta.raise_for_status()

        for vaga in resposta.json().get("jobs", []):
            titulo = vaga.get("title", "Sem título")
            link   = vaga.get("absolute_url", "")
            local  = vaga.get("location", {}).get("name", "Não informado")

            # ── DATA: Greenhouse não expõe data na API pública ────────
            # Marcamos None — o filtro vai tratar com tolerância máxima
            vagas_encontradas.append({
                "titulo":   titulo,
                "empresa":  empresa_nome,
                "local":    local,
                "link":     link,
                "fonte":    "Greenhouse",
                "data_pub": None,
            })

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except requests.exceptions.HTTPError as e:
        if "404" in str(e):
            print(f"   ⚠️  {empresa_nome} não encontrada no Greenhouse.")
        else:
            print(f"   ⚠️  Erro HTTP: {e}")
    except Exception as e:
        print(f"   ⚠️  Erro inesperado Greenhouse: {e}")

    return vagas_encontradas


def buscar_todas_greenhouse() -> list[dict]:
    todas = []
    for nome, slug in EMPRESAS_GREENHOUSE.items():
        todas.extend(buscar_vagas_greenhouse(nome, slug))
        time.sleep(1)
    return todas


# ── FONTE 3: Indeed ───────────────────────────────────────────────────────────

def buscar_vagas_indeed(cargo: str, local: str = "Brasil") -> list[dict]:
    vagas_encontradas = []
    cargo_url = cargo.replace(" ", "+")
    local_url = local.replace(" ", "+")
    url = f"https://br.indeed.com/jobs?q={cargo_url}&l={local_url}&sort=date"

    try:
        print(f"\n🔍 [Indeed] Buscando: '{cargo}'...")
        resposta = requests.get(url, headers=HEADERS, timeout=10)
        resposta.raise_for_status()

        soup  = BeautifulSoup(resposta.text, "html.parser")
        cards = soup.find_all("div", class_="job_seen_beacon")
        if not cards:
            cards = soup.find_all("div", attrs={"data-testid": "slider_container"})

        for card in cards[:15]:
            try:
                titulo_tag  = card.find("h2", class_="jobTitle")
                empresa_tag = card.find("span", attrs={"data-testid": "company-name"})
                local_tag   = card.find("div", attrs={"data-testid": "text-location"})
                link_tag    = card.find("a", class_="jcs-JobTitle")

                titulo     = titulo_tag.get_text(strip=True)  if titulo_tag  else "Sem título"
                empresa    = empresa_tag.get_text(strip=True) if empresa_tag else "Empresa não informada"
                local_vaga = local_tag.get_text(strip=True)   if local_tag   else "Não informado"
                link       = ("https://br.indeed.com" + link_tag["href"]) if link_tag and link_tag.get("href") else ""

                vagas_encontradas.append({
                    "titulo":   titulo,
                    "empresa":  empresa,
                    "local":    local_vaga,
                    "link":     link,
                    "fonte":    "Indeed",
                    "data_pub": None,  # Indeed não expõe data de forma confiável no scraping
                })
            except Exception:
                continue

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except requests.exceptions.HTTPError as e:
        print(f"   ⚠️  Erro HTTP Indeed: {e}")
    except Exception as e:
        print(f"   ⚠️  Erro inesperado Indeed: {e}")

    return vagas_encontradas


# ── FONTE 4: LinkedIn RSS ─────────────────────────────────────────────────────

def buscar_linkedin_rss(termo: str) -> list[dict]:
    vagas_encontradas = []
    termo_codificado  = urllib.parse.quote(termo)
    url = f"https://www.linkedin.com/jobs/search-api/feed?keywords={termo_codificado}&location=Brazil&geoId=106057199"

    try:
        print(f"\n🔍 [LinkedIn] Buscando: '{termo}'...")
        resposta = requests.get(url, headers=HEADERS, timeout=10)

        if resposta.status_code == 200:
            soup  = BeautifulSoup(resposta.text, 'xml')
            itens = soup.find_all('item')

            for item in itens:
                titulo  = item.find('title').text.strip() if item.find('title') else "Vaga sem título"
                link    = item.find('link').text.strip()  if item.find('link')  else ""
                empresa = "Não especificada (LinkedIn)"

                if " em " in titulo:
                    partes = titulo.split(" em ")
                    titulo  = partes[0]
                    empresa = partes[1]
                elif " at " in titulo:
                    partes = titulo.split(" at ")
                    titulo  = partes[0]
                    empresa = partes[1]

                # ── DATA: RSS tem pubDate ─────────────────────────────
                pub_date_tag = item.find('pubDate')
                data_pub = _parse_data(pub_date_tag.text if pub_date_tag else None)

                vagas_encontradas.append({
                    "titulo":   titulo,
                    "empresa":  empresa,
                    "local":    "Brasil",
                    "link":     link,
                    "fonte":    "LinkedIn (RSS)",
                    "data_pub": data_pub,
                })

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except Exception as e:
        print(f"   ⚠️  Erro inesperado [LinkedIn RSS]: {e}")

    return vagas_encontradas


# ── FONTE 5: LinkedIn Posts (DuckDuckGo) ──────────────────────────────────────

def buscar_linkedin_posts(termo: str) -> list[dict]:
    print(f"  🕵️‍♂️ Caçando posts ocultos no LinkedIn para: {termo}")
    vagas_encontradas = []

    query   = f'site:linkedin.com/posts "vaga" "{termo}"'
    url     = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    payload = {"q": query}

    try:
        resposta = requests.post(url, headers=headers, data=payload, timeout=15)
        if resposta.status_code == 200:
            soup       = BeautifulSoup(resposta.text, 'lxml')
            resultados = soup.find_all('div', class_='result')

            for res in resultados:
                elem_titulo = res.find('h2', class_='result__title')
                elem_link   = res.find('a', class_='result__url')

                if elem_titulo and elem_link:
                    titulo_bruto = elem_titulo.text.strip()
                    link         = elem_link.get('href', '')

                    if '//duckduckgo.com/l/?' in link:
                        parsed = urllib.parse.urlparse(link)
                        link   = urllib.parse.parse_qs(parsed.query).get('uddg', [link])[0]

                    if 'linkedin.com/posts' in link:
                        vagas_encontradas.append({
                            'titulo':   f"[POST] {titulo_bruto[:60]}...",
                            'empresa':  'Postagem do LinkedIn',
                            'local':    'Brasil (Verificar post)',
                            'link':     link,
                            'fonte':    'LinkedIn Posts',
                            'data_pub': None,  # DuckDuckGo não retorna data
                        })
    except Exception as e:
        print(f"  ❌ Erro ao buscar posts no DuckDuckGo: {e}")

    return vagas_encontradas


# ── Exibição ──────────────────────────────────────────────────────────────────

def exibir_vagas(vagas: list[dict]) -> None:
    if not vagas:
        print("\n❌ Nenhuma vaga encontrada.")
        return

    print(f"\n{'='*60}")
    print(f"  ✅ {len(vagas)} vaga(s) encontrada(s)")
    print(f"{'='*60}")

    for numero, vaga in enumerate(vagas, start=1):
        data_str = vaga['data_pub'].strftime('%d/%m/%Y') if vaga.get('data_pub') else "Data n/d"
        print(f"\n[{numero:02d}] {vaga['titulo']}")
        print(f"     Empresa     : {vaga['empresa']}")
        print(f"     Local       : {vaga['local']}")
        print(f"     Publicada   : {data_str}")
        print(f"     Fonte       : {vaga['fonte']}")
        print(f"     Link        : {vaga['link']}")
        print(f"     {'-'*52}")


if __name__ == "__main__":
    todas = []
    todas.extend(buscar_vagas_gupy("analista antifraude"))
    time.sleep(1)
    todas.extend(buscar_todas_greenhouse())
    todas.extend(buscar_vagas_indeed("analista antifraude"))
    time.sleep(1)
    todas.extend(buscar_linkedin_rss("analista antifraude"))
    time.sleep(1)
    exibir_vagas(todas)
    print(f"\n📊 Total: {len(todas)} vaga(s)")
