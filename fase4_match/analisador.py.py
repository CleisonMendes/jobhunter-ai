"""
==============================================
  JOBHUNTER AI — Fase 4: Match Score
==============================================
Compara o perfil do candidato com os dados da vaga
e gera uma pontuação de aderência (0 a 100+).
"""

def extrair_palavras_chave(perfil: dict) -> list:
    """Extrai todas as palavras úteis do perfil.json para usar no match"""
    palavras = []
    
    # Se o perfil tiver listas de habilidades, extraímos diretamente
    for chave, valor in perfil.items():
        if isinstance(valor, list):
            for item in valor:
                palavras.append(str(item).lower())
        elif isinstance(valor, str):
            # Adiciona strings isoladas dividindo-as por espaços
            palavras.extend(valor.lower().split())
            
    # Termos de peso (garantia de pontuação para o seu foco)
    termos_essenciais = ["antifraude", "chargeback", "fraude", "backoffice", "python", "sql", "dados", "ia"]
    palavras.extend(termos_essenciais)
    
    # Remove duplicados
    return list(set(palavras))

def calcular_match(vagas_filtradas: list[dict], perfil: dict) -> list[dict]:
    """
    Calcula o score de cada vaga com base nas palavras-chave do perfil.
    """
    print("\n[FASE 4] A calcular a pontuação de aderência (Match Score)...")
    
    palavras_perfil = extrair_palavras_chave(perfil)
    vagas_pontuadas = []

    for vaga in vagas_filtradas:
        score = 0
        titulo_vaga = vaga.get('titulo', '').lower()
        
        # Lógica de pontuação baseada no título
        for palavra in palavras_perfil:
            # Palavra exata ou parte importante do título
            if palavra in titulo_vaga:
                # Dá um peso maior a termos críticos
                if palavra in ["antifraude", "chargeback", "python"]:
                    score += 30
                else:
                    score += 10
        
        # Guarda a pontuação na própria vaga
        vaga['match_score'] = score
        vagas_pontuadas.append(vaga)
        
    # Ordena a lista: vagas com maior score ficam em primeiro lugar (reverse=True)
    vagas_pontuadas.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    
    return vagas_pontuadas

def exibir_ranking(vagas_pontuadas: list[dict], limite: int = 10) -> None:
    """Mostra o Top X de vagas com melhor Match Score."""
    print(f"\n{'='*60}")
    print(f"  🏆 TOP {limite} VAGAS MAIS ALINHADAS COM O SEU PERFIL")
    print(f"{'='*60}")
    
    # Filtra apenas vagas que tiveram alguma pontuação e limita o resultado
    melhores_vagas = [v for v in vagas_pontuadas if v['match_score'] > 0][:limite]
    
    if not melhores_vagas:
        print("\n❌ Nenhuma vaga obteve pontuação alta o suficiente nesta execução.")
        return

    for numero, vaga in enumerate(melhores_vagas, start=1):
        print(f"\n[{numero:02d}] {vaga['titulo']}")
        print(f"     Match Score : {vaga['match_score']} pts ⭐")
        print(f"     Empresa     : {vaga['empresa']}")
        print(f"     Local       : {vaga['local']}")
        print(f"     Fonte       : {vaga['fonte']}")
        print(f"     Link        : {vaga['link']}")
        print(f"     {'-'*52}")