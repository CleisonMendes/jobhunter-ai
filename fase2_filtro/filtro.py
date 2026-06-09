"""
==============================================
  JOBHUNTER AI — Fase 2: Filtro Inteligente
  Bloco 2: Pré-filtro refinado + termos compostos
==============================================
"""

# ── Palavras-chave por categoria ─────────────────────────────────────────────
#
# BLOCO 2 — Refinamento do pré-filtro:
# Adicionados termos compostos específicos para reduzir falsos positivos.
# Termos genéricos como "data" e "dados" foram movidos para baixa prioridade
# para não deixar passar vagas de Data Engineer Sênior irrelevantes.

PALAVRAS_CHAVE = {

    # Alta prioridade — área principal (peso 3)
    "alta": [
        "analista antifraude",
        "analista de antifraude",
        "analista chargeback",
        "analista de chargeback",
        "analista prevenção fraude",
        "prevenção de fraudes",
        "analista de fraude",
        "fraud analyst",
        "fraud prevention",
        "antifraude",
        "anti-fraude",
        "chargeback",
        "fraude",
        "fraud",
        "disputas",
        "contestação",
        "contestacao",
    ],

    # Média prioridade — skills técnicas relevantes (peso 2)
    "media": [
        "analista de dados",
        "data analyst",
        "analista backoffice",
        "analista back office",
        "backoffice financeiro",
        "back office financeiro",
        "automação de processos",
        "process automation",
        "analista financeiro",
        "analista de operações",
        "python",
        "sql",
        "qa financeiro",
        "qualidade financeiro",
        "fintech",
        "pagamentos",
        "payments",
        "automação",
    ],

    # Baixa prioridade — contexto amplo (peso 1)
    # Termos genéricos ficam aqui para não inflar o score de vagas irrelevantes
    "baixa": [
        "dados",
        "data",
        "banco",
        "financeiro",
        "risco",
        "risk",
        "compliance",
        "crédito",
        "pix",
        "cartão",
        "investimentos",
        "sdr",
        "qualidade",
        "qa",
    ]
}

# ── Títulos que devem ser barrados mesmo com score alto ──────────────────────
# Evita que vagas claramente fora do perfil passem pelo filtro de relevância
TITULOS_BLOQUEADOS = [
    "sênior", "senior", "sr.",
    "lead", "staff", "principal",
    "coordenador", "gerente", "manager",
    "diretor", "head", "cto", "cfo",
    "engenheiro de dados", "data engineer",
    "cientista de dados", "data scientist",
    "machine learning", "ml engineer",
    "devops", "sre", "platform engineer",
    "front-end", "frontend", "back-end", "backend",
    "mobile", "ios", "android",
    "designer", "ux", "ui",
    "product manager", "product owner",
    "scrum master", "agile coach",
    "assessoria de investimentos",
    "sales development",
]

# ── Localidades brasileiras válidas ──────────────────────────────────────────
LOCAIS_BRASIL = [
    "são paulo", "rio de janeiro", "minas gerais", "bahia", "paraná",
    "santa catarina", "rio grande do sul", "pernambuco", "ceará", "goiás",
    "espírito santo", "mato grosso", "pará", "amazonas", "maranhão",
    "paraíba", "rio grande do norte", "piauí", "alagoas", "sergipe",
    "tocantins", "rondônia", "acre", "amapá", "roraima",
    "sp", "rj", "mg", "ba", "pr", "sc", "rs", "pe", "ce", "go",
    "brasil", "brazil", "remoto", "remote", "híbrido", "hybrid",
    "não informado",
]

LOCAIS_BLOQUEADOS = [
    "canada", "usa", "united states", "united kingdom", "uk",
    "australia", "germany", "france", "spain", "portugal",
    "mexico", "colombia", "argentina", "chile", "peru",
    "india", "china", "japan", "latam",
]


def is_vaga_brasil(vaga: dict) -> bool:
    local = (vaga.get("local") or "").lower()
    for bloqueado in LOCAIS_BLOQUEADOS:
        if bloqueado in local:
            return False
    for valido in LOCAIS_BRASIL:
        if valido in local:
            return True
    return True  # dúvida = deixa passar


def is_titulo_bloqueado(titulo: str) -> bool:
    """Retorna True se o título contiver algum termo bloqueado."""
    titulo_lower = titulo.lower()
    return any(termo in titulo_lower for termo in TITULOS_BLOQUEADOS)


def remover_duplicatas(vagas: list[dict]) -> list[dict]:
    """Remove duplicatas por link."""
    vistos = set()
    unicas = []
    for vaga in vagas:
        link = vaga.get("link", "")
        if link not in vistos:
            vistos.add(link)
            unicas.append(vaga)
    return unicas


def filtrar_vagas(vagas: list[dict]) -> list[dict]:
    """
    Filtra e pontua vagas com base nas palavras-chave definidas.

    Pontuação:
      - palavra de alta prioridade  → +3 pontos
      - palavra de média prioridade → +2 pontos
      - palavra de baixa prioridade → +1 ponto

    Vagas com título bloqueado são descartadas mesmo com score alto.
    """
    vagas = remover_duplicatas(vagas)

    vagas_brasil = [v for v in vagas if is_vaga_brasil(v)]
    descartadas_pais = len(vagas) - len(vagas_brasil)
    if descartadas_pais > 0:
        print(f"  🌎 {descartadas_pais} vaga(s) descartada(s) por serem fora do Brasil")

    # Descarta títulos claramente fora do perfil
    vagas_relevantes = [v for v in vagas_brasil if not is_titulo_bloqueado(v.get('titulo', ''))]
    descartadas_titulo = len(vagas_brasil) - len(vagas_relevantes)
    if descartadas_titulo > 0:
        print(f"  🚫 {descartadas_titulo} vaga(s) descartada(s) por título fora do perfil")

    vagas_filtradas = []

    for vaga in vagas_relevantes:
        texto = f"{vaga['titulo']} {vaga['empresa']}".lower()

        pontuacao        = 0
        palavras_achadas = []

        for categoria, palavras in PALAVRAS_CHAVE.items():
            for palavra in palavras:
                if palavra.lower() in texto:
                    if categoria == "alta":
                        pontuacao += 3
                    elif categoria == "media":
                        pontuacao += 2
                    else:
                        pontuacao += 1
                    palavras_achadas.append(palavra)

        if pontuacao > 0:
            vaga_com_score = vaga.copy()
            vaga_com_score["relevancia"]       = pontuacao
            vaga_com_score["palavras_achadas"] = list(set(palavras_achadas))
            vagas_filtradas.append(vaga_com_score)

    vagas_filtradas.sort(key=lambda v: v["relevancia"], reverse=True)
    return vagas_filtradas


def exibir_resultado_filtro(vagas_originais: list[dict], vagas_filtradas: list[dict]) -> None:
    print(f"\n{'='*60}")
    print(f"  📊 RESULTADO DO FILTRO")
    print(f"{'='*60}")
    print(f"  Vagas encontradas : {len(vagas_originais)}")
    print(f"  Após filtro       : {len(vagas_filtradas)}")
    print(f"  Descartadas       : {len(vagas_originais) - len(vagas_filtradas)}")
    print(f"{'='*60}")

    if not vagas_filtradas:
        print("\n❌ Nenhuma vaga relevante encontrada com os filtros atuais.")
        print("💡 Dica: adicione mais palavras-chave em PALAVRAS_CHAVE")
        return

    for numero, vaga in enumerate(vagas_filtradas, start=1):
        if vaga["relevancia"] >= 6:
            icone = "🔥"
        elif vaga["relevancia"] >= 3:
            icone = "✅"
        else:
            icone = "🔶"

        print(f"\n{icone} [{numero:02d}] {vaga['titulo']}")
        print(f"      Empresa  : {vaga['empresa']}")
        print(f"      Local    : {vaga['local']}")
        print(f"      Score    : {vaga['relevancia']} pontos")
        print(f"      Match    : {', '.join(vaga['palavras_achadas'])}")
        print(f"      Link     : {vaga['link']}")
        print(f"      {'-'*50}")


if __name__ == "__main__":
    vagas_exemplo = [
        {"titulo": "Analista Antifraude Pleno", "empresa": "XP Inc.", "local": "São Paulo/SP", "link": "https://exemplo.com/1", "fonte": "Gupy"},
        {"titulo": "Analista de Chargeback Jr", "empresa": "PicPay", "local": "São Paulo/SP", "link": "https://exemplo.com/2", "fonte": "Gupy"},
        {"titulo": "Analista de Dados - Python", "empresa": "Nubank", "local": "Remoto", "link": "https://exemplo.com/3", "fonte": "Gupy"},
        {"titulo": "Sênior Data Engineer", "empresa": "Stone", "local": "Remoto", "link": "https://exemplo.com/4", "fonte": "Greenhouse"},
        {"titulo": "Assessoria de Investimentos", "empresa": "XP Inc.", "local": "São Paulo/SP", "link": "https://exemplo.com/5", "fonte": "Greenhouse"},
        {"titulo": "Desenvolvedor Front-End", "empresa": "Startup XYZ", "local": "Remoto", "link": "https://exemplo.com/6", "fonte": "Gupy"},
    ]
    vagas_filtradas = filtrar_vagas(vagas_exemplo)
    exibir_resultado_filtro(vagas_exemplo, vagas_filtradas)
