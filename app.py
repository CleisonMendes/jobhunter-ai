import streamlit as st
import sqlite3
import pandas as pd
import json
import os

st.set_page_config(page_title="JobHunter AI", page_icon="🤖", layout="wide")

# ==========================================
# CSS — formatação condicional e visual
# ==========================================
st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem !important; }
.kpi-card {
    background: #f8f9fa;
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 0.5rem;
}
.score-ouro  { color: #3B6D11; font-weight: 600; }
.score-prata { color: #854F0B; font-weight: 600; }
.score-atenc { color: #A32D2D; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. BARRA LATERAL (PERFIL + FILTROS)
# ==========================================
try:
    with open("fase3_perfil/perfil.json", "r", encoding="utf-8") as f:
        perfil = json.load(f)

    st.sidebar.header("👤 Perfil Ativo")
    st.sidebar.write(f"**Nome:** {perfil.get('nome', 'N/A')}")
    st.sidebar.write(f"**Cargo:** {perfil.get('cargo_atual', 'N/A')}")
    st.sidebar.write(f"**Empresa:** {perfil.get('empresa_atual', 'N/A')}")

    with st.sidebar.expander("🎓 Formação Acadêmica"):
        formacao = perfil.get("formacao", {})
        if isinstance(formacao, dict):
            st.write(f"**Curso:** {formacao.get('curso', 'N/A')}")
            st.write(f"**Local:** {formacao.get('instituicao', 'N/A')}")
            st.write(f"**Status:** {formacao.get('status', 'N/A')} ({formacao.get('conclusao_prevista', '')})")
        else:
            st.write(formacao)

    with st.sidebar.expander("📜 Cursos e Certificações"):
        for cert in perfil.get("certificacoes", []):
            st.write(f"- {cert}")

    with st.sidebar.expander("🎯 Áreas Alvo"):
        preferencias = perfil.get("preferencias_vaga", {})
        for area in preferencias.get("areas", []):
            st.write(f"- {area}")

    with st.sidebar.expander("🛠️ Habilidades Mapeadas"):
        for hab in perfil.get("habilidades", []):
            st.write(f"- {hab}")

    st.sidebar.success("✅ Sincronizado com a IA")

except Exception:
    st.sidebar.warning("⏳ Aguardando IA processar o perfil.json...")

# ── Filtros na sidebar ──────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.header("🎚️ Filtros")

score_min = st.sidebar.slider("Score mínimo de match", 0, 100, 0, step=5)

fontes_disponiveis = ["Todas", "Gupy", "Greenhouse", "LinkedIn Posts", "Indeed"]
fonte_filtro = st.sidebar.selectbox("Filtrar por fonte", fontes_disponiveis)

# ==========================================
# CABEÇALHO
# ==========================================
st.title("🤖 JobHunter AI — Painel de Controle")
st.caption("Monitoramento em tempo real da sua automação de caça a vagas.")

# ==========================================
# 2. LEITURA DO BANCO DE DADOS
# ==========================================
db_path = "vagas_enviadas.db"

if not os.path.exists(db_path):
    st.warning("⏳ Banco de dados ainda não foi criado. Aguarde a próxima execução.")
    st.stop()

conn = sqlite3.connect(db_path)

# Tenta ler colunas extras se existirem (match_score, titulo, empresa, fonte)
try:
    df = pd.read_sql_query("SELECT * FROM enviadas", conn)
except Exception as e:
    st.error(f"Erro ao ler o banco: {e}")
    conn.close()
    st.stop()

conn.close()

if df.empty:
    st.info("O banco de dados está pronto, mas nenhuma vaga inédita foi salva ainda.")
    st.stop()

# Normaliza colunas
df['data_envio'] = pd.to_datetime(df['data_envio'])
df['data_envio'] = df['data_envio'] - pd.Timedelta(hours=3)
df['Data'] = df['data_envio'].dt.date

# Colunas opcionais — preenche com fallback se não existirem
for col, fallback in [('match_score', 0), ('titulo', '—'), ('empresa', '—'), ('fonte', '—'), ('local', '—')]:
    if col not in df.columns:
        df[col] = fallback

df['match_score'] = pd.to_numeric(df['match_score'], errors='coerce').fillna(0).astype(int)

# ── Aplica filtros ──────────────────────────────────────────────────
df_filtrado = df[df['match_score'] >= score_min].copy()
if fonte_filtro != "Todas":
    df_filtrado = df_filtrado[df_filtrado['fonte'] == fonte_filtro]

# ==========================================
# 3. KPIs — Cards de Métricas
# ==========================================
st.subheader("📊 Resumo da Execução")

vagas_ouro  = (df_filtrado['match_score'] >= 80).sum()
vagas_prata = ((df_filtrado['match_score'] >= 50) & (df_filtrado['match_score'] < 80)).sum()
vagas_atenc = (df_filtrado['match_score'] < 50).sum()
score_medio = int(df_filtrado['match_score'].mean()) if not df_filtrado.empty else 0
ultima_captura = df['data_envio'].max().strftime("%d/%m/%Y %H:%M") if not df.empty else "—"

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔥 Vagas inéditas",    len(df))
c2.metric("🎯 Após filtros",      len(df_filtrado))
c3.metric("⭐ Score médio",       f"{score_medio}%")
c4.metric("🥇 Vagas ouro (≥80)", vagas_ouro)
c5.metric("⏱️ Última captura",   ultima_captura)

st.divider()

# ==========================================
# 4. TABELA COM FORMATAÇÃO CONDICIONAL
# ==========================================
st.subheader("🏆 Ranking de Vagas")

if df_filtrado.empty:
    st.info("Nenhuma vaga encontrada com os filtros selecionados.")
else:
    def colorir_score(val):
        if val >= 80:
            return 'background-color: #EAF3DE; color: #3B6D11; font-weight: 600;'
        elif val >= 50:
            return 'background-color: #FAEEDA; color: #854F0B; font-weight: 600;'
        else:
            return 'background-color: #FCEBEB; color: #A32D2D; font-weight: 600;'

    def badge_status(val):
        if val >= 80:   return '🥇 Ouro'
        elif val >= 50: return '🥈 Prata'
        else:           return '🔴 Atenção'

    df_tabela = df_filtrado[['data_envio', 'titulo', 'empresa', 'fonte', 'local', 'match_score', 'link']].copy()
    df_tabela = df_tabela.sort_values('match_score', ascending=False)
    df_tabela['status'] = df_tabela['match_score'].apply(badge_status)
    df_tabela.columns = ['Data/Hora', 'Cargo', 'Empresa', 'Fonte', 'Local', 'Score', 'Link', 'Status']
    df_tabela['Data/Hora'] = df_tabela['Data/Hora'].dt.strftime('%d/%m %H:%M')

    styled = (
        df_tabela.style
        .map(colorir_score, subset=['Score']) # <--- Mudamos de applymap para map
        .format({'Score': '{}%'})
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ==========================================
# 5. GRÁFICO DE ÁREA — Tendência de mercado
# ==========================================
st.subheader("📈 Tendência do Mercado (Vagas por Dia)")

vagas_por_dia = df.groupby('Data').size().reset_index(name='Vagas')
vagas_por_dia['Data'] = pd.to_datetime(vagas_por_dia['Data'])
vagas_por_dia = vagas_por_dia.set_index('Data')

if not vagas_por_dia.empty:
    # Preenche dias sem vagas com 0 para deixar o gráfico contínuo
    vagas_por_dia = vagas_por_dia.reindex(
        pd.date_range(vagas_por_dia.index.min(), vagas_por_dia.index.max(), freq='D'),
        fill_value=0
    )
    vagas_por_dia.index.name = 'Data'
    st.area_chart(vagas_por_dia, color="#378ADD")
else:
    st.info("Dados insuficientes para o gráfico de tendência.")

# ── Score médio por dia (linha separada) ───────────────────────────
if 'match_score' in df.columns and df['match_score'].sum() > 0:
    score_por_dia = df[df['match_score'] > 0].groupby('Data')['match_score'].mean().round(1).reset_index()
    score_por_dia.columns = ['Data', 'Score Médio']
    score_por_dia['Data'] = pd.to_datetime(score_por_dia['Data'])
    score_por_dia = score_por_dia.set_index('Data')

    st.caption("Score médio de aderência por dia")
    st.line_chart(score_por_dia, color="#639922")

st.divider()

# ==========================================
# 6. HISTÓRICO COMPLETO
# ==========================================
with st.expander("🔗 Histórico completo de links enviados"):
    df_hist = df[['data_envio', 'link']].sort_values('data_envio', ascending=False).copy()
    df_hist['data_envio'] = df_hist['data_envio'].dt.strftime('%d/%m/%Y %H:%M')
    df_hist.columns = ['Data/Hora', 'Link']
    st.dataframe(df_hist, use_container_width=True, hide_index=True)
