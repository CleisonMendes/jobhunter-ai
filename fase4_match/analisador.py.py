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
    """Filtra as vagas básicas e usa IA para analisar contexto e gerar dossiê."""
    print("\n[FASE 4] Triagem Híbrida e Inteligência Analítica (Match 2.0)...")
    import os
    import json
    
    # 1. PRÉ-FILTRO (Evitar estouro de limite da API)
    vagas_pre_aprovadas = []
    termos_chave = ["antifraude", "chargeback", "fraude", "risco", "dados", "data", "python", "sql", "backoffice"]
    termos_barrar = ["sênior", "senior", "lead", "staff", "coordenador", "gerente", "manager"]

    for vaga in vagas_filtradas:
        titulo = vaga.get('titulo', '').lower()
        if any(termo in titulo for termo in termos_chave) and not any(termo in titulo for termo in termos_barrar):
            vagas_pre_aprovadas.append(vaga)

    if not vagas_pre_aprovadas:
        return []

    # 2. ANÁLISE IA (Match Score 2.0 e Dossiê)
    vagas_pontuadas = []
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("  ⚠️ GEMINI_API_KEY não encontrada. Abortando IA Analítica.")
        return vagas_pre_aprovadas

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    # Resumo do seu perfil para a IA ler mais rápido
    perfil_resumido = {
        "cargo": perfil.get("cargo_atual"),
        "habilidades": perfil.get("habilidades"),
        "areas": perfil.get("preferencias_vaga", {}).get("areas")
    }

    limite_analise = 10 # Limita para não estourar a API gratuita
    print(f"  🧠 Analisando as {len(vagas_pre_aprovadas[:limite_analise])} melhores vagas com Gemini...")

    for vaga in vagas_pre_aprovadas[:limite_analise]:
        prompt = f"""
        Você é um consultor de carreira avaliando uma vaga para o candidato.
        Perfil do candidato: {json.dumps(perfil_resumido, ensure_ascii=False)}
        Vaga: "{vaga['titulo']}" na empresa "{vaga['empresa']}"

        Avalie a aderência de 0 a 100. Se a aderência for >= 75, crie um dossiê.
        
        Retorne EXATAMENTE neste formato JSON:
        {{
            "score": 85,
            "resumo": "Uma frase curta explicando o porquê da nota.",
            "perguntas_entrevista": ["Pergunta técnica 1", "Pergunta comportamental 2"],
            "mensagem_linkedin": "Uma mensagem curta de 2 linhas para o candidato abordar o recrutador dessa empresa no LinkedIn ressaltando a experiência dele."
        }}
        """
        try:
            resposta = model.generate_content(prompt)
            texto = resposta.text.strip()
            
            # Limpeza do JSON
            if texto.startswith("```"):
                texto = texto.split("\n", 1)[1].rsplit("\n", 1)[0]
            if texto.startswith("json"):
                texto = texto.split("\n", 1)[1]

            analise = json.loads(texto)
            vaga['match_score'] = analise.get('score', 0)
            vaga['resumo_ia'] = analise.get('resumo', '')
            vaga['perguntas'] = analise.get('perguntas_entrevista', [])
            vaga['mensagem_linkedin'] = analise.get('mensagem_linkedin', '')
            
            vagas_pontuadas.append(vaga)
            time.sleep(4) # Pausa de 4s para respeitar o limite de 15 requisições por minuto do Google
            
        except Exception as e:
            print(f"  ❌ Erro de IA na vaga {vaga['titulo']}: {e}")
            vaga['match_score'] = 10
            vagas_pontuadas.append(vaga)

    # Ordena as vagas com maior pontuação primeiro
    vagas_pontuadas.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    return vagas_pontuadas
