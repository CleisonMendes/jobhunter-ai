"""
==============================================
  JOBHUNTER AI — Fase 1: Buscador de Vagas
==============================================
Fontes suportadas:
  - Gupy        (API pública)
  - Greenhouse  (API pública — XP, Stone, Nubank, etc)
  - Indeed      (scraping via HTML)
  - LinkedIn    (feed RSS público Brasil)

Conceitos aprendidos nessa fase:
  - Funções (def)
  - Estruturas de repetição (for)
  - Listas e dicionários
  - Requests (requisição HTTP)
  - BeautifulSoup (parsing HTML)
  - Tratamento de erros (try/except)
"""

import requests
from bs4 import BeautifulSoup
import time
import urllib.parse  # Necessário para codificar termos de busca na URL


# ── Configurações gerais ──────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Empresas financeiras monitoradas no Greenhouse
# Chave = nome exibido | Valor = slug usado na URL da API
EMPRESAS_GREENHOUSE = {
    "Nubank":       "nubank",
    "Stone":        "stone",
    "XP Inc.":      "xpinc",
    "Pagar.me":     "pagarme",
    "Creditas":     "creditas",
    "Dock":         "dock",
    "Quanto":       "quanto",
}


# ── FONTE 1: Gupy ─────────────────────────────────────────────────────────────

def buscar_vagas_gupy(cargo: str) -> list[dict]:
    """
    Busca vagas na API pública da Gupy.

    Parâmetros:
        cargo (str): termo de busca, ex: "analista antifraude"

    Retorna:
        list[dict]: lista de vagas
    """
    vagas_encontradas = []
    url = "https://portal.api.gupy.io/api/v1/jobs"

    parametros = {
        "jobName": cargo,
        "limit":   20,
        "offset":  0
    }

    try:
        print(f"\n🔍 [Gupy] Buscando: '{cargo}'...")

        resposta = requests.get(url, params=parametros, headers=HEADERS, timeout=10)
        resposta.raise_for_status()

        dados       = resposta.json()
        lista_vagas = dados.get("data", [])

        for vaga in lista_vagas:
            titulo  = vaga.get("name", "Sem título")
            empresa = vaga.get("company", {}).get("name", "Empresa não informada")
            link    = vaga.get("jobUrl", "Link não disponível")
            cidade  = vaga.get("city", "")
            estado  = vaga.get("state", "")
            local   = f"{cidade}/{estado}" if cidade else "Remoto / Não informado"

            vagas_encontradas.append({
                "titulo":  titulo,
                "empresa": empresa,
                "local":   local,
                "link":    link,
                "fonte":   "Gupy"
            })

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except requests.exceptions.Timeout:
        print("   ⚠️  Timeout — Gupy demorou para responder.")
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Sem conexão com a internet.")
    except requests.exceptions.HTTPError as erro:
        print(f"   ⚠️  Erro HTTP: {erro}")
    except Exception as erro:
        print(f"   ⚠️  Erro inesperado: {erro}")

    return vagas_encontradas


# ── FONTE 2: Greenhouse ───────────────────────────────────────────────────────

def buscar_vagas_greenhouse(empresa_nome: str, empresa_slug: str) -> list[dict]:
    """
    Busca TODAS as vagas abertas de uma empresa no Greenhouse.
    O Greenhouse tem API pública por empresa — sem necessidade de autenticação.

    Parâmetros:
        empresa_nome (str): nome para exibição, ex: "Nubank"
        empresa_slug (str): slug da empresa na URL, ex: "nubank"

    Retorna:
        list[dict]: lista de vagas da empresa
    """
    vagas_encontradas = []

    # URL padrão da API pública do Greenhouse
    url = f"https://boards-api.greenhouse.io/v1/boards/{empresa_slug}/jobs"

    try:
        print(f"\n🔍 [Greenhouse] Buscando vagas em: {empresa_nome}...")

        resposta = requests.get(url, headers=HEADERS, timeout=10)
        resposta.raise_for_status()

        dados       = resposta.json()
        lista_vagas = dados.get("jobs", [])

        for vaga in lista_vagas:
            titulo = vaga.get("title", "Sem título")
            link   = vaga.get("absolute_url", "Link não disponível")

            # Localização vem dentro de "location"
            local_info = vaga.get("location", {})
            local      = local_info.get("name", "Não informado")

            vagas_encontradas.append({
                "titulo":  titulo,
                "empresa": empresa_nome,
                "local":   local,
                "link":    link,
                "fonte":   "Greenhouse"
            })

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except requests.exceptions.Timeout:
        print(f"   ⚠️  Timeout — {empresa_nome} demorou para responder.")
    except requests.exceptions.HTTPError as erro:
        # 404 = empresa não encontrada no Greenhouse, não é erro crítico
        if "404" in str(erro):
            print(f"   ⚠️  {empresa_nome} não encontrada no Greenhouse.")
        else:
            print(f"   ⚠️  Erro HTTP: {erro}")
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Sem conexão com a internet.")
    except Exception as erro:
        print(f"   ⚠️  Erro inesperado: {erro}")

    return vagas_encontradas


def buscar_todas_greenhouse() -> list[dict]:
    """
    Percorre todas as empresas em EMPRESAS_GREENHOUSE e coleta vagas.

    Retorna:
        list[dict]: todas as vagas encontradas no Greenhouse
    """
    todas = []

    for nome, slug in EMPRESAS_GREENHOUSE.items():
        vagas = buscar_vagas_greenhouse(nome, slug)
        todas.extend(vagas)
        time.sleep(1)   # pausa entre empresas — boa prática

    return todas


# ── FONTE 3: Indeed ───────────────────────────────────────────────────────────

def buscar_vagas_indeed(cargo: str, local: str = "Brasil") -> list[dict]:
    """
    Busca vagas no Indeed Brasil via scraping de HTML.
    
    Atenção: scraping é menos estável que API — o Indeed pode bloquear
    ou mudar o layout. Se parar de funcionar, é normal.

    Parâmetros:
        cargo (str): cargo buscado, ex: "analista antifraude"
        local (str): localidade, padrão "Brasil"

    Retorna:
        list[dict]: lista de vagas
    """
    vagas_encontradas = []

    # Monta a URL de busca do Indeed Brasil
    cargo_url = cargo.replace(" ", "+")
    local_url = local.replace(" ", "+")
    url = f"https://br.indeed.com/jobs?q={cargo_url}&l={local_url}&sort=date"

    try:
        print(f"\n🔍 [Indeed] Buscando: '{cargo}'...")

        resposta = requests.get(url, headers=HEADERS, timeout=10)
        resposta.raise_for_status()

        soup = BeautifulSoup(resposta.text, "html.parser")

        # Indeed usa a classe "job_seen_beacon" para cada card de vaga
        cards = soup.find_all("div", class_="job_seen_beacon")

        if not cards:
            # Tenta seletor alternativo caso o layout mude
            cards = soup.find_all("div", attrs={"data-testid": "slider_container"})

        for card in cards[:15]:   # limita a 15 por busca
            try:
                # Título da vaga
                titulo_tag = card.find("h2", class_="jobTitle")
                titulo     = titulo_tag.get_text(strip=True) if titulo_tag else "Sem título"

                # Nome da empresa
                empresa_tag = card.find("span", attrs={"data-testid": "company-name"})
                empresa     = empresa_tag.get_text(strip=True) if empresa_tag else "Empresa não informada"

                # Localização
                local_tag = card.find("div", attrs={"data-testid": "text-location"})
                local_vaga = local_tag.get_text(strip=True) if local_tag else "Não informado"

                # Link — Indeed usa links relativos, precisa montar a URL completa
                link_tag = card.find("a", class_="jcs-JobTitle")
                if link_tag and link_tag.get("href"):
                    link = "https://br.indeed.com" + link_tag["href"]
                else:
                    link = "Link não disponível"

                vagas_encontradas.append({
                    "titulo":  titulo,
                    "empresa": empresa,
                    "local":   local_vaga,
                    "link":    link,
                    "fonte":   "Indeed"
                })

            except Exception:
                # Se um card falhar, continua para o próximo
                continue

        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")

    except requests.exceptions.Timeout:
        print("   ⚠️  Timeout — Indeed demorou para responder.")
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Sem conexão com a internet.")
    except requests.exceptions.HTTPError as erro:
        print(f"   ⚠️  Erro HTTP Indeed: {erro}")
    except Exception as erro:
        print(f"   ⚠️  Erro inesperado: {erro}")

    return vagas_encontradas


# ── FONTE 4: LinkedIn ─────────────────────────────────────────────────────────

def buscar_linkedin_rss(termo: str) -> list[dict]:
    """
    Busca vagas no LinkedIn através do feed RSS público (Sem restrições de API).
    
    Parâmetros:
        termo (str): cargo buscado, ex: "analista antifraude"

    Retorna:
        list[dict]: lista de vagas
    """
    vagas_encontradas = []
    
    # Codifica o termo para a URL (ex: 'analista de fraude' vira 'analista%20de%20fraude')
    termo_codificado = urllib.parse.quote(termo)
    
    # URL do feed de empregos do LinkedIn focado no Brasil (geoId 106057199)
    url = f"https://www.linkedin.com/jobs/search-api/feed?keywords={termo_codificado}&location=Brazil&geoId=106057199"
    
    try:
        print(f"\n🔍 [LinkedIn] Buscando: '{termo}'...")
        resposta = requests.get(url, headers=HEADERS, timeout=10)
        
        if resposta.status_code == 200:
            # O feed RSS do LinkedIn usa formato XML. O BeautifulSoup lê perfeitamente.
            soup = BeautifulSoup(resposta.text, 'xml')
            itens = soup.find_all('item')
            
            for item in itens:
                titulo = item.find('title').text.strip() if item.find('title') else "Vaga sem título"
                link = item.find('link').text.strip() if item.find('link') else ""
                
                # O LinkedIn costuma colocar a empresa no formato "Título da Vaga na Empresa"
                empresa = "Não especificada (LinkedIn)"
                if " em " in titulo:
                    partes = titulo.split(" em ")
                    titulo = partes[0]
                    empresa = partes[1]
                elif " at " in titulo:
                    partes = titulo.split(" at ")
                    titulo = partes[0]
                    empresa = partes[1]
                
                vagas_encontradas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": "Brasil",
                    "link": link,
                    "fonte": "LinkedIn (RSS)"
                })
                
        print(f"   ✅ {len(vagas_encontradas)} vaga(s) encontrada(s)")
        
    except requests.exceptions.Timeout:
        print("   ⚠️  Timeout — LinkedIn demorou para responder.")
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Sem conexão com a internet.")
    except Exception as e:
        print(f"   ⚠️  Erro inesperado [LinkedIn]: {e}")
        
    return vagas_encontradas


# ── Função de exibição ────────────────────────────────────────────────────────

def exibir_vagas(vagas: list[dict]) -> None:
    """
    Exibe as vagas encontradas de forma organizada no terminal.
    """
    if not vagas:
        print("\n❌ Nenhuma vaga encontrada.")
        return

    print(f"\n{'='*60}")
    print(f"  ✅ {len(vagas)} vaga(s) encontrada(s)")
    print(f"{'='*60}")

    for numero, vaga in enumerate(vagas, start=1):
        print(f"\n[{numero:02d}] {vaga['titulo']}")
        print(f"     Empresa : {vaga['empresa']}")
        print(f"     Local   : {vaga['local']}")
        print(f"     Fonte   : {vaga['fonte']}")
        print(f"     Link    : {vaga['link']}")
        print(f"     {'-'*52}")


# ── Teste isolado ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("     JOBHUNTER AI — Fase 1: Buscador (v3)")
    print("=" * 60)

    todas = []

    # Gupy
    todas.extend(buscar_vagas_gupy("analista antifraude"))
    time.sleep(1)

    # Greenhouse — todas as empresas monitoradas
    todas.extend(buscar_todas_greenhouse())

    # Indeed
    todas.extend(buscar_vagas_indeed("analista antifraude"))
    time.sleep(1)
    
    # LinkedIn
    todas.extend(buscar_linkedin_rss("analista antifraude"))
    time.sleep(1)

    exibir_vagas(todas)
    print(f"\n📊 Total: {len(todas)} vaga(s)")