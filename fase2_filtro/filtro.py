"""
==============================================
  JOBHUNTER AI — Fase 2: Filtro Inteligente
==============================================
Objetivo: Filtrar apenas vagas relevantes
          usando palavras-chave do seu perfil.

Conceitos aprendidos nessa fase:
  - Strings (lower, in, split)
  - Listas e list comprehension
  - Funções com múltiplos parâmetros
  - Condicionais (if/elif/else)
  - Dicionários
"""

# ── Palavras-chave por categoria ──────────────────────────────────────────────

# Cada categoria tem um peso diferente — quanto mais específica, maior o peso
PALAVRAS_CHAVE = {

    # Alta prioridade — área principal do Cleison
    "alta": [
        "antifraude",
        "anti-fraude",
        "chargeback",
        "fraude",
        "fraud",
        "prevenção de fraudes",
        "analista de fraude",
        "fraud analyst",
        "fraud prevention",
        "disputas",
        "contestação",
    ],

    # Média prioridade — skills técnicas
    "media": [
        "python",
        "sql",
        "dados",
        "data",
        "automação",
        "automation",
        "qa",
        "qualidade",
        "analise de dados",
        "data analyst",
        "backoffice",
        "back office",
        "financeiro",
        "fintech",
        "pagamentos",
        "payments",
    ],

    # Baixa prioridade — contexto geral
    "baixa": [
        "sdr",
        "investimentos",
        "banco",
        "cartão",
        "crédito",
        "débito",
        "pix",
        "compliance",
        "risco",
        "risk",
    ]
}


# ── Localidades brasileiras válidas ──────────────────────────────────────────

# Vagas com essas palavras no campo "local" são aceitas
LOCAIS_BRASIL = [
    "são paulo", "rio de janeiro", "minas gerais", "bahia", "paraná",
    "santa catarina", "rio grande do sul", "pernambuco", "ceará", "goiás",
    "espírito santo", "mato grosso", "pará", "amazonas", "maranhão",
    "paraíba", "rio grande do norte", "piauí", "alagoas", "sergipe",
    "tocantins", "rondônia", "acre", "amapá", "roraima",
    "sp", "rj", "mg", "ba", "pr", "sc", "rs", "pe", "ce", "go",
    "brasil", "brazil", "remoto", "remote", "híbrido", "hybrid",
    "não informado",   # vagas sem local definido também entram
]

# Localidades estrangeiras para bloquear explicitamente
LOCAIS_BLOQUEADOS = [
    "canada", "usa", "united states", "united kingdom", "uk",
    "australia", "germany", "france", "spain", "portugal",
    "mexico", "colombia", "argentina", "chile", "peru",
    "india", "china", "japan", "latam",
]


def is_vaga_brasil(vaga: dict) -> bool:
    """
    Verifica se a vaga é do Brasil ou remota sem restrição geográfica.

    Parâmetros:
        vaga (dict): dados da vaga

    Retorna:
        bool: True se a vaga for elegível para candidatura no Brasil
    """
    local = (vaga.get("local") or "").lower()

    # Bloqueia explicitamente locais estrangeirosconhecidos
    for bloqueado in LOCAIS_BLOQUEADOS:
        if bloqueado in local:
            return False

    # Aceita se tiver qualquer estado/cidade brasileira ou "remoto"
    for valido in LOCAIS_BRASIL:
        if valido in local:
            return True

    # Se não identificou nada, deixa passar (melhor não descartar por dúvida)
    return True


def remover_duplicatas(vagas: list[dict]) -> list[dict]:
    """
    Remove vagas duplicadas com base no link.

    Parâmetros:
        vagas (list[dict]): lista com possíveis duplicatas

    Retorna:
        list[dict]: lista sem duplicatas
    """
    vistos = set()
    unicas = []

    for vaga in vagas:
        link = vaga.get("link", "")
        if link not in vistos:
            vistos.add(link)
            unicas.append(vaga)

    return unicas


# ── Função principal de filtro ────────────────────────────────────────────────

def filtrar_vagas(vagas: list[dict]) -> list[dict]:
    """
    Filtra e pontua vagas com base nas palavras-chave definidas.

    Cada vaga recebe uma pontuação de relevância:
      - palavra de alta prioridade  → +3 pontos
      - palavra de média prioridade → +2 pontos
      - palavra de baixa prioridade → +1 ponto

    Parâmetros:
        vagas (list[dict]): lista bruta de vagas

    Retorna:
        list[dict]: apenas vagas relevantes, ordenadas por pontuação
    """
    # Remove duplicatas antes de qualquer coisa
    vagas = remover_duplicatas(vagas)

    # Remove vagas fora do Brasil
    vagas_brasil = [v for v in vagas if is_vaga_brasil(v)]
    descartadas_pais = len(vagas) - len(vagas_brasil)
    if descartadas_pais > 0:
        print(f"  🌎 {descartadas_pais} vaga(s) descartada(s) por serem fora do Brasil")

    vagas_filtradas = []

    for vaga in vagas_brasil:
        # Junta título + empresa em um único texto para verificar
        texto = f"{vaga['titulo']} {vaga['empresa']}".lower()

        pontuacao          = 0
        palavras_achadas   = []

        # Verifica cada categoria de palavras-chave
        for categoria, palavras in PALAVRAS_CHAVE.items():
            for palavra in palavras:
                if palavra.lower() in texto:

                    # Adiciona pontos de acordo com a prioridade
                    if categoria == "alta":
                        pontuacao += 3
                    elif categoria == "media":
                        pontuacao += 2
                    else:
                        pontuacao += 1

                    palavras_achadas.append(palavra)

        # Só inclui a vaga se tiver pelo menos 1 ponto
        if pontuacao > 0:
            vaga_com_score = vaga.copy()           # não modifica a vaga original
            vaga_com_score["relevancia"]        = pontuacao
            vaga_com_score["palavras_achadas"]  = list(set(palavras_achadas))
            vagas_filtradas.append(vaga_com_score)

    # Ordena do mais relevante para o menos relevante
    vagas_filtradas.sort(key=lambda v: v["relevancia"], reverse=True)

    return vagas_filtradas


def exibir_resultado_filtro(vagas_originais: list[dict], vagas_filtradas: list[dict]) -> None:
    """
    Mostra o resultado do filtro com comparativo antes/depois.

    Parâmetros:
        vagas_originais (list[dict]): lista completa antes do filtro
        vagas_filtradas (list[dict]): lista após o filtro
    """
    print(f"\n{'='*60}")
    print(f"  📊 RESULTADO DO FILTRO")
    print(f"{'='*60}")
    print(f"  Vagas encontradas : {len(vagas_originais)}")
    print(f"  Após filtro       : {len(vagas_filtradas)}")

    descartadas = len(vagas_originais) - len(vagas_filtradas)
    print(f"  Descartadas       : {descartadas}")
    print(f"{'='*60}")

    if not vagas_filtradas:
        print("\n❌ Nenhuma vaga relevante encontrada com os filtros atuais.")
        print("💡 Dica: adicione mais palavras-chave em PALAVRAS_CHAVE")
        return

    for numero, vaga in enumerate(vagas_filtradas, start=1):
        # Define emoji de relevância visual
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


# ── Uso direto (para testar a fase isolada) ───────────────────────────────────

if __name__ == "__main__":
    """
    Para testar sem a Fase 1, cria algumas vagas de exemplo.
    Na integração real, você passa a lista vinda do buscador.py
    """

    # Simula vagas como se viessem da Fase 1
    vagas_exemplo = [
        {
            "titulo": "Analista Antifraude Pleno",
            "empresa": "XP Inc.",
            "local": "São Paulo/SP",
            "link": "https://exemplo.com/vaga/1",
            "fonte": "Gupy"
        },
        {
            "titulo": "Desenvolvedor Front-End",
            "empresa": "Startup XYZ",
            "local": "Remoto",
            "link": "https://exemplo.com/vaga/2",
            "fonte": "Gupy"
        },
        {
            "titulo": "Analista de Chargeback Jr",
            "empresa": "PicPay",
            "local": "São Paulo/SP",
            "link": "https://exemplo.com/vaga/3",
            "fonte": "Gupy"
        },
        {
            "titulo": "Analista de Dados - Python",
            "empresa": "Nubank",
            "local": "Remoto",
            "link": "https://exemplo.com/vaga/4",
            "fonte": "Gupy"
        },
        {
            "titulo": "Designer Gráfico",
            "empresa": "Agência Creative",
            "local": "Rio de Janeiro/RJ",
            "link": "https://exemplo.com/vaga/5",
            "fonte": "Gupy"
        },
    ]

    vagas_filtradas = filtrar_vagas(vagas_exemplo)
    exibir_resultado_filtro(vagas_exemplo, vagas_filtradas)
