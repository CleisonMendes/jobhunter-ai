"""
==============================================
  JOBHUNTER AI — main.py
  Integração Completa: Fases 1 a 7 (PDF + IA)
==============================================
Fontes ativas:
  ✅ Gupy       — API pública
  ✅ Greenhouse — XP, Stone, Nubank, Creditas...
  ✅ Indeed     — scraping Brasil
  ✅ LinkedIn   — feed RSS Brasil
  ✅ LinkedIn   — Posts (Mercado Oculto)
  ✅ Gemini IA  — Leitura automática de PDF
"""

import sys
import time
import google.generativeai as genai
from pathlib import Path

# Mantemos apenas as pastas das fases 1, 2 e 3
sys.path.append(str(Path(__file__).parent / "fase1_mvp"))
sys.path.append(str(Path(__file__).parent / "fase2_filtro"))
sys.path.append(str(Path(__file__).parent / "fase3_perfil"))

from filtro     import filtrar_vagas, exibir_resultado_filtro
from perfil     import carregar_perfil, exibir_perfil
from buscador   import buscar_vagas_gupy, buscar_todas_greenhouse, buscar_vagas_indeed, buscar_linkedin_rss, buscar_linkedin_posts

# 💥 IMPORTAÇÃO NOVA: O Cérebro Leitor de PDF
from leitor_pdf import checar_e_atualizar_perfil


# ====================================================================
# ── FASE 4: MATCH SCORE ─────────────────────────────────────────────
# ====================================================================

def extrair_palavras_chave(perfil: dict) -> list:
    palavras = []
    for chave, valor in perfil.items():
        if isinstance(valor, list):
            for item in valor:
                palavras.append(str(item).lower())
        elif isinstance(valor, str):
            palavras.extend(valor.lower().split())
            
    termos_essenciais = ["antifraude", "chargeback", "fraude", "backoffice", "python", "sql", "dados", "ia"]
    palavras.extend(termos_essenciais)
    return list(set(palavras))

def calcular_match(vagas_filtradas: list[dict], perfil: dict) -> list[dict]:
    print("\n[FASE 4] Triagem Híbrida e Inteligência Analítica (Match 2.0)...")
    import os
    import json
    import re
    
    vagas_pre_aprovadas = []
    termos_chave = ["antifraude", "chargeback", "fraude", "risco", "dados", "data", "python", "sql", "backoffice"]
    termos_barrar = ["sênior", "senior", "lead", "staff", "coordenador", "gerente", "manager"]

    for vaga in vagas_filtradas:
        titulo = vaga.get('titulo', '').lower()
        if any(termo in titulo for termo in termos_chave) and not any(termo in titulo for termo in termos_barrar):
            vagas_pre_aprovadas.append(vaga)

    if not vagas_pre_aprovadas:
        return []

    vagas_pontuadas = []
    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    perfil_resumido = {
        "cargo": perfil.get("cargo_atual"),
        "habilidades": perfil.get("habilidades"),
        "areas": perfil.get("preferencias_vaga", {}).get("areas")
    }

    limite_analise = 5
    for vaga in vagas_pre_aprovadas[:limite_analise]:
        prompt = f"""
        Você é um consultor. Analise esta vaga para o candidato: {json.dumps(perfil_resumido, ensure_ascii=False)}
        Vaga: "{vaga['titulo']}" na empresa "{vaga['empresa']}"

        Avalie a aderência de 0 a 100.
        Retorne APENAS um objeto JSON válido (começando com {{ e terminando com }}):
        {{
            "score": 85,
            "resumo": "Explicação curta.",
            "perguntas_entrevista": ["p1", "p2"],
            "mensagem_linkedin": "abordagem curta."
        }}
        """
        try:
            resposta = model.generate_content(prompt)
            texto_bruto = resposta.text.strip()
            
            # --- ESPIÃO ---
            print(f"  🔍 IA Respondeu para '{vaga['titulo'][:20]}...': {texto_bruto}")
            # --------------
            
            match = re.search(r'\{.*\}', texto_bruto, re.DOTALL)
            if match:
                analise = json.loads(match.group(0))
                vaga['match_score'] = analise.get('score', 0)
                vaga['resumo_ia'] = analise.get('resumo', '')
                vaga['perguntas'] = analise.get('perguntas_entrevista', [])
                vaga['mensagem_linkedin'] = analise.get('mensagem_linkedin', '')
                vagas_pontuadas.append(vaga)
                time.sleep(4)
            else:
                # Se não achou JSON, força erro
                raise ValueError("Não encontrei JSON")
            
        except Exception as e:
            print(f"  ❌ ERRO na IA para '{vaga['titulo'][:20]}': {e}")
            vaga['match_score'] = 10
            vagas_pontuadas.append(vaga)

    vagas_pontuadas.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    return vagas_pontuadas

def exibir_ranking(vagas_pontuadas: list[dict], limite: int = 15) -> None:
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
    import requests
    import os
    import sqlite3

    print("\n[FASE 5] Verificando vagas inéditas no Banco de Dados...")

    conn = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enviadas (
            link TEXT PRIMARY KEY,
            data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    melhores_vagas = [v for v in vagas_pontuadas if v['match_score'] > 0]
    vagas_ineditas = []

    for vaga in melhores_vagas:
        link = vaga['link']
        cursor.execute("SELECT 1 FROM enviadas WHERE link = ?", (link,))
        if cursor.fetchone() is None:
            vagas_ineditas.append(vaga)
            if len(vagas_ineditas) >= limite:
                break

    if not vagas_ineditas:
        print("  🤫 Nenhuma vaga nova nesta rodada. Nada foi enviado para evitar spam.")
        conn.close()
        return

    print(f"  🔥 Encontrada(s) {len(vagas_ineditas)} vaga(s) inédita(s)! Enviando...")

    # Montando a mensagem VIP com Dossiê da IA
    mensagem = f"🚀 <b>NOVAS VAGAS INÉDITAS ({len(vagas_ineditas)})</b> 🚀\n\n"
    
    for numero, vaga in enumerate(vagas_ineditas, start=1):
        link = vaga['link']
        titulo = vaga['titulo'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        empresa = vaga['empresa'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        score = vaga.get('match_score', 0)
        
        mensagem += f"<b>[{numero:02d}] {titulo}</b>\n"
        mensagem += f"🏢 {empresa} | 📍 {vaga['local']}\n"
        mensagem += f"⭐ <b>Match Score: {score}%</b>\n"
        
        if vaga.get('resumo_ia'):
            mensagem += f"🤖 <i>{vaga['resumo_ia']}</i>\n"
        
        mensagem += f"🔗 <a href='{link}'>Acessar Vaga</a>\n\n"
        
        # Só anexa o dossiê se a vaga for realmente boa (Score alto)
        if score >= 75 and vaga.get('perguntas'):
            mensagem += f"<b>💡 DOSSIÊ DE ENTREVISTA</b>\n"
            for p in vaga['perguntas']:
                mensagem += f"❓ {p}\n"
            mensagem += f"💬 <b>Abordagem LinkedIn:</b>\n<i>{vaga['mensagem_linkedin']}</i>\n"
            
        mensagem += "───────────────────\n\n"
        
        cursor.execute("INSERT OR IGNORE INTO enviadas (link) VALUES (?)", (link,))

    conn.commit()
    conn.close()

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
    print("     Gupy · Greenhouse · Indeed · LinkedIn · PDF Reader")
    print("=" * 60)

    # ── FASE 3: Perfil (AGORA COM INTELIGÊNCIA ARTIFICIAL) ────────
    print("\n[FASE 3] Carregando perfil do candidato...")
    
    # Aciona o leitor de PDF. Se houver arquivo, ele atualiza o JSON.
    try:
        checar_e_atualizar_perfil()
    except Exception as e:
        print(f"  ⚠️ Aviso: Erro no leitor de PDF. Usando perfil atual. Detalhes: {e}")
        
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

    # — LinkedIn (Busca normal via RSS) —
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
        
    # — LinkedIn Posts (Mercado Oculto via DuckDuckGo) —
    print("\n🔍 Acessando o mercado oculto de posts no LinkedIn...")
    termos_ocultos = ["antifraude", "chargeback"]
    for termo in termos_ocultos:
        vagas = buscar_linkedin_posts(termo)
        todas_vagas.extend(vagas)
        time.sleep(2)

    print(f"\n  📥 Total bruto coletado: {len(todas_vagas)} vaga(s)")

    # ── FASE 2: Filtro ────────────────────────────────────────────
    print("\n[FASE 2] Aplicando filtro — removendo fora do Brasil...")
    vagas_filtradas = filtrar_vagas(todas_vagas)
    exibir_resultado_filtro(todas_vagas, vagas_filtradas)

    # ── FASE 4: Match Score ───────────────────────────────────────
    vagas_com_score = calcular_match(vagas_filtradas, perfil)
    exibir_ranking(vagas_com_score, limite=15)

    # ── FASE 5: Telegram (com persistência SQLite) ────────────────
    enviar_para_telegram(vagas_com_score, limite=15)

    # ── Resumo ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline completo finalizado!")
    print(f"  → {len(todas_vagas)} vagas brutas coletadas")
    print(f"  → {len(vagas_filtradas)} vagas relevantes após filtro")
    print(f"  → Vagas inéditas filtradas pelo Banco de Dados")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
