"""
==============================================
  JOBHUNTER AI — Fase 2: Filtro Inteligente
  Bloco 3+: Filtro de recência + bônus de data
==============================================

Regras de recência:
  - > 30 dias → DESCARTADA (muito antiga)
  - 16–30 dias → baixa prioridade (sem bônus)
  - 8–15 dias  → intermediária (+2 pts bônus)
  - 0–7 dias   → alta prioridade (+5 pts bônus)
  - sem data   → aceita sem bônus (Greenhouse, Indeed, Posts)
"""

from datetime import datetime, timezone

# ── Configuração de recência ──────────────────────────────────────────────────

DIAS_MAXIMOS       = 30   # vagas mais antigas são descartadas
DIAS_INTERMEDIARIO = 15   # a partir daqui ganha bônus intermediário
DIAS_ALTA          = 7    # a partir daqui ganha bônus alto

BONUS_ALTA          = 5
BONUS_INTERMEDIARIO = 2
BONUS_BAIXA         = 0


# ── Palavras-chave por categoria ──────────────────────────────────────────────

PALAVRAS_CHAVE = {
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


# ── Funções auxiliares ────────────────────────────────────────────────────────

def is_vaga_brasil(vaga: dict) -> bool:
    local = (vaga.get("local") or "").lower()
    for bloqueado in LOCAIS_BLOQUEADOS:
        if bloqueado in local:
            return False
    for valido in LOCAIS_BRASIL:
        if valido in local:
            return True
    return True


def is_titulo_bloqueado(titulo: str) -> bool:
    titulo_lower = titulo.lower()
    return any(termo in titulo_lower for termo in TITULOS_BLOQUEADOS)


def calcular_bonus_recencia(data_pub) -> tuple[int, str]:
    """
    Calcula o bônus de recência e o label da faixa.

    Retorna:
        (bonus: int, label: str)
        bonus = 0 e label = "sem data" quando data_pub é None
        bonus = -999 indica que a vaga deve ser DESCARTADA
    """
    if data_pub is None:
        return 0, "📅 sem data"

    agora = datetime.now(timezone.utc)

    # Garante que data_pub tem timezone
    if data_pub.tzinfo is None:
        data_pub = data_pub.replace(tzinfo=timezone.utc)

    dias = (agora - data_pub).days

    if dias > DIAS_MAXIMOS:
        return -999, f"❌ {dias}d (muito antiga)"
    elif dias <= DIAS_ALTA:
        return BONUS_ALTA, f"🔥 {dias}d (alta)"
    elif dias <= DIAS_INTERMEDIARIO:
        return BONUS_INTERMEDIARIO, f"🟡 {dias}d (intermediária)"
    else:
        return BONUS_BAIXA, f"⚪ {dias}d (baixa)"


def remover_duplicatas(vagas: list[dict]) -> list[dict]:
    vistos = set()
    unicas = []
    for vaga in vagas:
        link = vaga.get("link", "")
        if link not in vistos:
            vistos.add(link)
            unicas.append(vaga)
    return unicas


# ── Função principal ──────────────────────────────────────────────────────────

def filtrar_vagas(vagas: list[dict]) -> list[dict]:
    """
    Filtra e pontua vagas com base em palavras-chave e recência.

    Pontuação base:
      - palavra alta   → +3
      - palavra média  → +2
      - palavra baixa  → +1

    Bônus de recência (somado ao score base):
      - 0–7 dias   → +5
      - 8–15 dias  → +2
      - 16–30 dias → +0
      - >30 dias   → DESCARTADA (se data disponível)
      - sem data   → aceita sem bônus
    """
    vagas = remover_duplicatas(vagas)

    # Filtra por localidade
    vagas_brasil = [v for v in vagas if is_vaga_brasil(v)]
    desc_pais = len(vagas) - len(vagas_brasil)
    if desc_pais > 0:
        print(f"  🌎 {desc_pais} vaga(s) descartada(s) por serem fora do Brasil")

    # Filtra por título
    vagas_relevantes = [v for v in vagas_brasil if not is_titulo_bloqueado(v.get('titulo', ''))]
    desc_titulo = len(vagas_brasil) - len(vagas_relevantes)
    if desc_titulo > 0:
        print(f"  🚫 {desc_titulo} vaga(s) descartada(s) por título fora do perfil")

    vagas_filtradas = []
    desc_antigas    = 0

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

        if pontuacao == 0:
            continue

        # Calcula bônus de recência
        bonus, label_recencia = calcular_bonus_recencia(vaga.get('data_pub'))

        if bonus == -999:
            desc_antigas += 1
            continue  # descarta vaga muito antiga

        vaga_com_score = vaga.copy()
        vaga_com_score["relevancia"]       = pontuacao + bonus
        vaga_com_score["palavras_achadas"] = list(set(palavras_achadas))
        vaga_com_score["recencia"]         = label_recencia
        vaga_com_score["bonus_recencia"]   = bonus
        vagas_filtradas.append(vaga_com_score)

    if desc_antigas > 0:
        print(f"  📅 {desc_antigas} vaga(s) descartada(s) por terem mais de {DIAS_MAXIMOS} dias")

    vagas_filtradas.sort(key=lambda v: v["relevancia"], reverse=True)
    return vagas_filtradas


# ── Exibição ──────────────────────────────────────────────────────────────────

def exibir_resultado_filtro(vagas_originais: list[dict], vagas_filtradas: list[dict]) -> None:
    print(f"\n{'='*60}")
    print(f"  📊 RESULTADO DO FILTRO")
    print(f"{'='*60}")
    print(f"  Vagas encontradas : {len(vagas_originais)}")
    print(f"  Após filtro       : {len(vagas_filtradas)}")
    print(f"  Descartadas       : {len(vagas_originais) - len(vagas_filtradas)}")
    print(f"{'='*60}")

    if not vagas_filtradas:
        print("\n❌ Nenhuma vaga relevante encontrada.")
        return

    for numero, vaga in enumerate(vagas_filtradas, start=1):
        if vaga["relevancia"] >= 8:
            icone = "🔥"
        elif vaga["relevancia"] >= 4:
            icone = "✅"
        else:
            icone = "🔶"

        recencia = vaga.get('recencia', '📅 sem data')
        bonus    = vaga.get('bonus_recencia', 0)
        bonus_str = f"+{bonus}pts" if bonus > 0 else ""

        print(f"\n{icone} [{numero:02d}] {vaga['titulo']}")
        print(f"      Empresa  : {vaga['empresa']}")
        print(f"      Local    : {vaga['local']}")
        print(f"      Score    : {vaga['relevancia']} pontos {bonus_str}")
        print(f"      Recência : {recencia}")
        print(f"      Match    : {', '.join(vaga['palavras_achadas'])}")
        print(f"      Link     : {vaga['link']}")
        print(f"      {'-'*50}")


if __name__ == "__main__":
    from buscador import buscar_vagas_gupy
    vagas = buscar_vagas_gupy("analista antifraude")
    filtradas = filtrar_vagas(vagas)
    exibir_resultado_filtro(vagas, filtradas)
