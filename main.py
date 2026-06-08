"""
==============================================
  JOBHUNTER AI — main.py
  Integração Completa: Fases 1 a 5 (Telegram)
==============================================
Fontes ativas:
  ✅ Gupy       — API pública
  ✅ Greenhouse — XP, Stone, Nubank, Creditas...
  ✅ Indeed     — scraping Brasil
  ✅ LinkedIn   — feed RSS Brasil

Execute com:
    py main.py
"""

import sys
import time
from pathlib import Path

# Mantemos apenas as pastas das fases 1, 2 e 3
sys.path.append(str(Path(__file__).parent / "fase1_mvp"))
sys.path.append(str(Path(__file__).parent / "fase2_filtro"))
sys.path.append(str(Path(__file__).parent / "fase3_perfil"))

from buscador import buscar_vagas_gupy, buscar_todas_greenhouse, buscar_vagas_indeed, buscar_linkedin_rss
from filtro   import filtrar_vagas, exibir_resultado_filtro
from perfil   import carregar_perfil, exibir_perfil


# ====================================================================
# ── CÓDIGO DA FASE 4 INTEGRADO AQUI (MATCH SCORE) ───────────────────
# ====================================================================

def extrair_palavras_chave(perfil: dict) -> list:
    """Extrai todas as palavras úteis do perfil.json para usar no match"""
    palavras = []
    for chave, valor in perfil.items():
        if isinstance(valor, list):
            for item in valor:
                palavras.append(str(item).lower())
        elif isinstance(valor, str):
            palavras.extend(valor.lower().split())
            
    # Termos de peso da sua área
    termos_essenciais = ["antifraude", "chargeback", "fraude", "backoffice", "python", "sql", "dados", "ia"]
    palavras.extend(termos_essenciais)
    return list(set(palavras))

def calcular_match(vagas_filtradas: list[dict], perfil: dict) -> list[dict]:
    """Calcula o score de cada vaga com base em pesos matemáticos refinados."""
    print("\n[FASE 4] Calculando a pontuação de aderência refinada (Match Score)...")
    vagas_pontuadas = []

    for vaga in vagas_filtradas:
        score = 0
        titulo_vaga = vaga.get('titulo', '').lower()
        
        # 1. PESO CRÍTICO: Foco Principal (100 pontos)
        termos_criticos = ["antifraude", "chargeback", "prevenção de fraude", "prevenção a fraude"]
        for termo in termos_criticos:
            if termo in titulo_vaga:
                score += 100
                
        # 2. PESO ALTO: Ferramentas e Dados (40 pontos)
        termos_altos = ["python", "sql", "dados", "data analyst", "bi"]
        for termo in termos_altos:
            if termo in titulo_vaga:
                score += 40
                
        # 3. PESO MÉDIO: Negócio e Suporte (20 pontos)
        termos_medios = ["financeiro", "backoffice", "risk", "risco", "compliance"]
        for termo in termos_medios:
            if termo in titulo_vaga:
                score += 20

        # 4. PENALIZAÇÃO: Níveis acima do alvo (-50 pontos)
        termos_barrar = ["sênior", "senior", "lead", "staff", "coordenador", "gerente", "manager"]
        for termo in termos_barrar:
            if termo in titulo_vaga:
                score -= 50
        
        # Garante que o score não seja negativo
        vaga['match_score'] = max(0, score)
        vagas_pontuadas.append(vaga)
        
    # Ordena as melhores vagas para o topo
    vagas_pontuadas.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    return vagas_pontuadas

def exibir_ranking(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    """Mostra o Top X de vagas com melhor Match Score."""
    print(f"\n{'='*60}")
    print(f"  🏆 TOP {limite} VAGAS MAIS ALINHADAS COM O SEU PERFIL")
    print(f"{'='*60}")
    
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

# ====================================================================
# ── FASE 5: ENVIO PARA O TELEGRAM COM BANCO DE DADOS (MEMÓRIA) ──────
# ====================================================================

def enviar_para_telegram(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    """Filtra vagas repetidas usando SQLite e envia apenas as inéditas para o Telegram."""
    import requests
    import os
    import sqlite3

    print("\n[FASE 5] Verificando vagas inéditas no Banco de Dados...")

    # Conecta ao banco de dados (será criado na raiz do projeto se não existir)
    conn = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()

    # Cria a tabela para guardar os links se ela não existir
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enviadas (
            link TEXT PRIMARY KEY,
            data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Pegar as credenciais do ambiente
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    # Filtra apenas vagas com score positivo
    melhores_vagas = [v for v in vagas_pontuadas if v['match_score'] > 0]
    
    vagas_ineditas = []

    # Testa vaga por vaga no banco de dados
    for vaga in melhores_vagas:
        link = vaga['link']
        cursor.execute("SELECT 1 FROM enviadas WHERE link = ?", (link,))
        if cursor.fetchone() is None:
            # Vaga não existe no banco, então é inédita!
            vagas_ineditas.append(vaga)
            
            # Se já atingimos o limite de envio para essa rodada, paramos de acumular
            if len(vagas_ineditas) >= limite:
                break

    if not vagas_ineditas:
        print("  🤫 Nenhuma vaga nova nesta rodada. Nada foi enviado para evitar spam.")
        conn.close()
        return

    print(f"  🔥 Encontrada(s) {len(vagas_ineditas)} vaga(s) inédita(s)! Enviando...")

    # Montando a mensagem com as INÉDITAS
    mensagem = f"🚀 <b>NOVAS VAGAS INÉDITAS ({len(vagas_ineditas)})</b> 🚀\n\n"
    
    for numero, vaga in enumerate(vagas_ineditas, start=1):
        titulo = vaga['titulo'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        empresa = vaga['empresa'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        mensagem += f"<b>[{numero:02d}] {titulo}</b>\n"
        mensagem += f"⭐ Score: {vaga['match_score']} pts\n"
        mensagem += f"🏢 {empresa} | 📍 {vaga['local']}\n"
        mensagem += f"🔗 <a href='{vaga['link']}'>Acessar Vaga</a>\n\n"
        
        # Salva o link no banco de dados para não repetir na próxima rodada
        cursor.execute("INSERT OR IGNORE INTO enviadas (link) VALUES (?)", (link,))

    conn.commit()
    conn.close()

    # Envia para a API do Telegram
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        resposta = requests.post(url, json=payload)
        if resposta.status_code == 200:
            print("  📱 ✅ Novidades enviadas com sucesso para o seu celular!")
        else:
            print(f"  ❌ Erro ao enviar para o Telegram: {resposta.text}")
    except Exception as e:
        print(f"  ❌ Erro de conexão com Telegram: {e}")


# ====================================================================


def main():
    print("\n" + "=" * 60)
    print("          🤖 JOBHUNTER AI — Sistema Completo")
    print("     Gupy · Greenhouse · Indeed · LinkedIn — Somente Brasil")
    print("=" * 60)

    # ── FASE 3: Perfil ────────────────────────────────────────────
    print("\n[FASE 3] Carregando perfil do candidato...")
    perfil = carregar_perfil()
    exibir_perfil(perfil)


    # ── FASE 1: Busca ─────────────────────────────────────────────
    print("\n[FASE 1] Iniciando busca de vagas...")
    todas_vagas = []

    # — Gupy —
    termos_gupy = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
        "analista financeiro",
        "backoffice financeiro",
        "analista de dados",
    ]

    for termo in termos_gupy:
        vagas = buscar_vagas_gupy(termo)
        todas_vagas.extend(vagas)
        time.sleep(1)

    # — Greenhouse —
    print("\n📡 Buscando nas empresas financeiras via Greenhouse...")
    vagas_gh = buscar_todas_greenhouse()
    todas_vagas.extend(vagas_gh)

    # — Indeed —
    termos_indeed = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
    ]

    for termo in termos_indeed:
        vagas = buscar_vagas_indeed(termo, "Brasil")
        todas_vagas.extend(vagas)
        time.sleep(1)

    # — LinkedIn —
    print("\n💼 Buscando no LinkedIn via RSS público...")
    termos_linkedin = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes"
    ]
    
    for termo in termos_linkedin:
        vagas = buscar_linkedin_rss(termo)
        todas_vagas.extend(vagas)
        time.sleep(1)

    print(f"\n  📥 Total bruto coletado: {len(todas_vagas)} vaga(s)")

    # ── FASE 2: Filtro ────────────────────────────────────────────
    print("\n[FASE 2] Aplicando filtro — removendo fora do Brasil...")
    vagas_filtradas = filtrar_vagas(todas_vagas)
    exibir_resultado_filtro(todas_vagas, vagas_filtradas)

    # ── FASE 4: Match Score ───────────────────────────────────────
    vagas_com_score = calcular_match(vagas_filtradas, perfil)
    exibir_ranking(vagas_com_score, limite=15)

    # ── FASE 5: Telegram ──────────────────────────────────────────
    enviar_para_telegram(vagas_com_score, limite=15)

    # ── Resumo ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline completo! Fases 1 a 5 integradas.")
    print(f"  → {len(todas_vagas)} vagas brutas coletadas")
    print(f"  → {len(vagas_filtradas)} vagas relevantes após filtro")
    print(f"  → Top 15 vagas enviadas para o Telegram")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
    
    
