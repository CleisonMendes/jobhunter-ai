"""
==============================================
  RADAR DE VAGAS — main.py (v2)
  Bloco 1: Deduplicação + DB Enriquecido + Descartadas
  Bloco 3: Alerta de Urgência + Relatório Semanal
  Bloco 4: Planilha Gestão de Vagas (Google Sheets)
  v2: pula vagas já vistas, nota com descrição completa, alerta de fonte quebrada,
      botões no Telegram + follow-up, Lever, checagem de vaga aberta
      (a lógica da análise e do envio agora está em analise_envio.py)
==============================================
"""

import sys
import time
import json
import re
import os
import sqlite3
import requests
from datetime import datetime, timedelta
from google import genai
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append(str(Path(__file__).parent / "fase1_mvp"))
sys.path.append(str(Path(__file__).parent / "fase2_filtro"))
sys.path.append(str(Path(__file__).parent / "fase3_perfil"))

from filtro      import filtrar_vagas, exibir_resultado_filtro
from perfil      import carregar_perfil, exibir_perfil
from buscador    import buscar_todas_greenhouse, buscar_linkedin_posts
from integracoes import buscar_vagas_gupy, registrar_na_planilha, filtrar_recentes

# ── NOVOS MÓDULOS (v2) ───────────────────────────────────────────────
from analise_envio  import (calcular_match, exibir_ranking, enviar_para_telegram,
                            _enviar_mensagem_telegram, _rotulo_idade, _prioridade)
from telegram_acoes import rotinas_telegram
from funil          import enviar_relatorio_funil
from saude_fontes   import verificar_e_alertar
from fontes_extra   import (buscar_todas_lever, LEVER_EMPRESAS,
                            buscar_todas_programathor, PROGRAMATHOR_ATIVO)


# ====================================================================
# ── UTILITÁRIO: TIMER ────────────────────────────────────────────────
# ====================================================================

class Timer:
    def __init__(self, nome):
        self.nome = nome

    def __enter__(self):
        self.inicio = time.time()
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.inicio
        print(f"  ⏱️  [{self.nome}] concluído em {elapsed:.1f}s")


# ====================================================================
# ── ITEM 2: DEDUPLICAÇÃO ─────────────────────────────────────────────
# ====================================================================

def deduplicar_vagas(vagas: list[dict]) -> list[dict]:
    print("\n[DEDUP] Removendo duplicatas...")
    vistas_por_link  = set()
    vistas_por_chave = set()
    unicas = []

    for vaga in vagas:
        link    = vaga.get('link', '').strip()
        titulo  = vaga.get('titulo', '').lower().strip()
        empresa = vaga.get('empresa', '').lower().strip()
        titulo_norm = re.sub(r'\s*[-|]\s*(linkedin|gupy|greenhouse|indeed).*$', '', titulo)
        chave = f"{titulo_norm[:40]}|{empresa[:30]}"

        if link and link in vistas_por_link:
            continue
        if chave in vistas_por_chave:
            continue
        if link:
            vistas_por_link.add(link)
        vistas_por_chave.add(chave)
        unicas.append(vaga)

    removidas = len(vagas) - len(unicas)
    print(f"  🧹 {removidas} duplicata(s) removida(s) → {len(unicas)} vagas únicas")
    return unicas


# ====================================================================
# ── ITEM 3: BANCO DE DESCARTADAS ─────────────────────────────────────
# ====================================================================

def salvar_descartadas(todas_vagas: list[dict], vagas_filtradas: list[dict]) -> None:
    links_aprovados = {v.get('link') for v in vagas_filtradas}
    descartadas = [v for v in todas_vagas if v.get('link') not in links_aprovados]

    if not descartadas:
        return

    conn   = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS descartadas (
            link          TEXT PRIMARY KEY,
            titulo        TEXT,
            empresa       TEXT,
            fonte         TEXT,
            local         TEXT,
            motivo        TEXT,
            data_descarte TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    inseridas = 0
    for vaga in descartadas:
        link  = vaga.get('link', '')
        local = (vaga.get('local') or '').lower()

        if any(p in local for p in ['united', 'mexico', 'colombia', 'argentina', 'usa', 'us', 'uk']):
            motivo = "Fora do Brasil"
        elif not link:
            motivo = "Link inválido"
        else:
            motivo = "Não passou no filtro de relevância"

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO descartadas (link, titulo, empresa, fonte, local, motivo)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                link,
                vaga.get('titulo', '—'),
                vaga.get('empresa', '—'),
                vaga.get('fonte', '—'),
                vaga.get('local', '—'),
                motivo
            ))
            if cursor.rowcount > 0:
                inseridas += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f"  🗃️  {inseridas} vaga(s) nova(s) registrada(s) em 'descartadas'")


# ====================================================================
# ── FASE 1: BUSCA PARALELA (+ saúde das fontes + Lever) ──────────────
# ====================================================================

TERMOS_GUPY     = ["analista antifraude", "analista chargeback", "prevenção de fraudes",
                   "analista financeiro", "backoffice financeiro", "analista de dados"]
TERMOS_LINKEDIN = ["antifraude", "chargeback"]


def buscar_todas_vagas_paralelo() -> list:
    print("\n[FASE 1] Buscando vagas em paralelo...")
    token   = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    # cliques nos botões do Telegram + lembretes de follow-up (a cada rodada)
    rotinas_telegram(token, chat_id)

    todas_vagas = []
    tarefas = [("gupy", t) for t in TERMOS_GUPY] + [("linkedin_posts", t) for t in TERMOS_LINKEDIN]
    nomes   = {"gupy": "Gupy", "linkedin_posts": "LinkedIn (posts)"}
    saude   = {nome: [0, ""] for nome in nomes.values()}   # fonte -> [qtd, erro]

    def executar_tarefa(args):
        fonte, termo = args
        try:
            if fonte == "gupy":
                return fonte, buscar_vagas_gupy(termo), ""
            if fonte == "linkedin_posts":
                return fonte, buscar_linkedin_posts(termo), ""
        except Exception as e:
            print(f"  ⚠️  Erro em {fonte} ({termo}): {e}")
            return fonte, [], f"{type(e).__name__}: {str(e)[:60]}"
        return fonte, [], ""

    with Timer("Buscas paralelas (Gupy + LinkedIn)"):
        with ThreadPoolExecutor(max_workers=8) as executor:
            futuros = {executor.submit(executar_tarefa, t): t for t in tarefas}
            for futuro in as_completed(futuros):
                fonte, resultado, erro = futuro.result()
                nome = nomes.get(fonte)
                if resultado:
                    todas_vagas.extend(resultado)
                    if nome:
                        saude[nome][0] += len(resultado)
                if erro and nome:
                    saude[nome][1] = erro

    with Timer("Greenhouse"):
        print("  📡 Buscando nas empresas financeiras via Greenhouse...")
        saude["Greenhouse"] = [0, ""]
        try:
            achadas = buscar_todas_greenhouse()
            todas_vagas.extend(achadas)
            saude["Greenhouse"][0] = len(achadas)
        except Exception as e:
            print(f"  ⚠️  Erro no Greenhouse: {e}")
            saude["Greenhouse"][1] = f"{type(e).__name__}: {str(e)[:60]}"

    if LEVER_EMPRESAS:
        with Timer("Lever"):
            saude["Lever"] = [0, ""]
            try:
                achadas = buscar_todas_lever()
                todas_vagas.extend(achadas)
                saude["Lever"][0] = len(achadas)
            except Exception as e:
                print(f"  ⚠️  Erro no Lever: {e}")
                saude["Lever"][1] = f"{type(e).__name__}: {str(e)[:60]}"

    if PROGRAMATHOR_ATIVO:
        with Timer("ProgramaThor"):
            saude["ProgramaThor"] = [0, ""]
            try:
                achadas = buscar_todas_programathor()
                todas_vagas.extend(achadas)
                saude["ProgramaThor"][0] = len(achadas)
            except Exception as e:
                print(f"  ⚠️  Erro no ProgramaThor: {e}")
                saude["ProgramaThor"][1] = f"{type(e).__name__}: {str(e)[:60]}"

    # alerta no Telegram se alguma fonte está quebrada há várias rodadas
    try:
        verificar_e_alertar({f: (q, e) for f, (q, e) in saude.items()}, token, chat_id)
    except Exception as e:
        print(f"  ⚠️  Não consegui checar a saúde das fontes: {e}")

    print(f"\n  📥 Total bruto coletado: {len(todas_vagas)} vaga(s)")
    return todas_vagas


# ====================================================================
# ── RELATÓRIO SEMANAL (domingo) + FUNIL ──────────────────────────────
# ====================================================================

def _ja_enviou_hoje(nome: str) -> bool:
    """Evita repetir o relatório a cada rodada do domingo. Registra no próprio banco."""
    hoje = datetime.utcnow().strftime('%Y-%m-%d')
    conn = sqlite3.connect("vagas_enviadas.db")
    conn.execute("CREATE TABLE IF NOT EXISTS relatorios_enviados (nome TEXT, dia TEXT, PRIMARY KEY (nome, dia))")
    ja = conn.execute("SELECT 1 FROM relatorios_enviados WHERE nome = ? AND dia = ?", (nome, hoje)).fetchone()
    if not ja:
        conn.execute("INSERT INTO relatorios_enviados VALUES (?, ?)", (nome, hoje))
        conn.commit()
    conn.close()
    return bool(ja)


def verificar_e_enviar_relatorio_semanal() -> None:
    """
    Roda todo domingo (uma vez por dia). Envia o resumo dos últimos 7 dias
    e, em seguida, o funil de candidaturas lido da planilha.
    """
    hoje = datetime.utcnow()

    # Só envia no domingo (weekday() == 6)
    if hoje.weekday() != 6:
        return
    if _ja_enviou_hoje("semanal"):
        return

    print("\n[RELATÓRIO SEMANAL] Domingo detectado — gerando relatório...")

    TOKEN   = os.environ.get("TELEGRAM_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    if not TOKEN or not CHAT_ID:
        print("  ⚠️  Telegram não configurado. Pulando relatório.")
        return

    conn   = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()

    sete_dias_atras = (hoje - timedelta(days=7)).strftime('%Y-%m-%d')

    # Vagas capturadas na semana
    cursor.execute("SELECT COUNT(*) FROM enviadas WHERE data_envio >= ?", (sete_dias_atras,))
    total_semana = cursor.fetchone()[0]

    # Score médio da semana
    cursor.execute("SELECT AVG(match_score) FROM enviadas WHERE data_envio >= ? AND match_score > 0", (sete_dias_atras,))
    score_medio = cursor.fetchone()[0]
    score_medio = round(score_medio, 1) if score_medio else 0

    # Vagas ouro na semana
    cursor.execute("SELECT COUNT(*) FROM enviadas WHERE data_envio >= ? AND match_score >= 85", (sete_dias_atras,))
    total_ouro = cursor.fetchone()[0]

    # Empresas que mais apareceram
    cursor.execute("""
        SELECT empresa, COUNT(*) as qtd FROM enviadas
        WHERE data_envio >= ?
        GROUP BY empresa ORDER BY qtd DESC LIMIT 5
    """, (sete_dias_atras,))
    top_empresas = cursor.fetchall()

    # Total histórico
    cursor.execute("SELECT COUNT(*) FROM enviadas")
    total_historico = cursor.fetchone()[0]

    conn.close()

    data_inicio = (hoje - timedelta(days=7)).strftime('%d/%m')
    data_fim    = hoje.strftime('%d/%m')

    mensagem  = f"📊 <b>RELATÓRIO SEMANAL — {data_inicio} a {data_fim}</b>\n"
    mensagem += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    mensagem += f"📥 <b>Vagas capturadas na semana:</b> {total_semana}\n"
    mensagem += f"⭐ <b>Score médio de aderência:</b> {score_medio}%\n"
    mensagem += f"🥇 <b>Vagas ouro (≥85%):</b> {total_ouro}\n"
    mensagem += f"📚 <b>Total histórico no banco:</b> {total_historico}\n\n"

    if top_empresas:
        mensagem += "🏢 <b>Empresas que mais apareceram:</b>\n"
        for empresa, qtd in top_empresas:
            mensagem += f"  • {empresa}: {qtd} vaga(s)\n"

    mensagem += "\n💡 <i>Dica: acesse o dashboard para ver o ranking completo.</i>\n"
    mensagem += "━━━━━━━━━━━━━━━━━━━━━━━━━"

    _enviar_mensagem_telegram(mensagem, TOKEN, CHAT_ID)
    print("  📊 ✅ Relatório semanal enviado!")

    # Funil de candidaturas (usa a planilha; se não houver, só avisa e segue)
    try:
        enviar_relatorio_funil()
    except Exception as e:
        print(f"  ⚠️  Funil não enviado: {e}")


# ====================================================================
# ── MAIN ─────────────────────────────────────────────────────────────
# ====================================================================

def main():
    inicio_total = time.time()

    print("\n" + "=" * 60)
    print("  🤖 RADAR DE VAGAS — Sistema Completo")
    print("  Gupy · Greenhouse · LinkedIn · Lever · ProgramaThor · Google Sheets")
    print("=" * 60)

    # Fase 3: Perfil
    print("\n[FASE 3] Carregando perfil do candidato...")
    # O perfil vem somente do fase3_perfil/perfil.json (o leitor de PDF não é mais usado)
    perfil = carregar_perfil()
    exibir_perfil(perfil)

    # Relatório semanal (roda antes do pipeline)
    try:
        verificar_e_enviar_relatorio_semanal()
    except Exception as e:
        print(f"  ⚠️  Erro no relatório semanal: {e}")

    # Fase 1: Busca paralela (inclui cliques do Telegram, follow-up e saúde das fontes)
    with Timer("FASE 1 — Busca total"):
        todas_vagas = buscar_todas_vagas_paralelo()

    # Deduplicação
    with Timer("DEDUP — Deduplicação"):
        todas_vagas = deduplicar_vagas(todas_vagas)

    # Recência: só vagas de até 30 dias, prioridade para as dos últimos 7
    with Timer("RECÊNCIA — Filtro de datas"):
        todas_vagas = filtrar_recentes(todas_vagas)

    # Fase 2: Filtro
    with Timer("FASE 2 — Filtro"):
        print("\n[FASE 2] Aplicando filtro — removendo fora do Brasil...")
        vagas_filtradas = filtrar_vagas(todas_vagas)
        exibir_resultado_filtro(todas_vagas, vagas_filtradas)

    # Salvar descartadas
    with Timer("DEDUP — Salvando descartadas"):
        salvar_descartadas(todas_vagas, vagas_filtradas)

    # Fase 4: Match Score (pula vagas já vistas, confere se está aberta, usa a descrição)
    with Timer("FASE 4 — Match Score"):
        vagas_com_score = calcular_match(vagas_filtradas, perfil)
        exibir_ranking(vagas_com_score, limite=15)

    # Fase 5: Telegram (uma mensagem por vaga, com botões) + banco + planilha
    with Timer("FASE 5 — Telegram + Planilha"):
        enviar_para_telegram(vagas_com_score, limite=15)

    # Resumo final
    tempo_total = time.time() - inicio_total
    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline completo em {tempo_total:.1f}s ({tempo_total/60:.1f} min)")
    print(f"  → {len(todas_vagas)} vagas únicas após deduplicação")
    print(f"  → {len(vagas_filtradas)} vagas relevantes após filtro")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
