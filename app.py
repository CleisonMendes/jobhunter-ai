import streamlit as st
import sqlite3
import pandas as pd
import json
import os

st.set_page_config(page_title="JobHunter AI", page_icon="🤖", layout="wide")

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem !important; }
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
        for area in perfil.get("preferencias_vaga", {}).get("areas", []):
            st.write(f"- {area}")

    with st.sidebar.expander("🛠️ Habilidades Mapeadas"):
        for hab in perfil.get("habilidades", []):
            st.write(f"- {hab}")

    st.sidebar.success("✅ Sincronizado com a IA")

except Exception:
    st.sidebar.warning("⏳ Aguardando IA processar o perfil.json...")

st.sidebar.divider()
st.sidebar.header("🎚️ Filtros")
score_min    = st.sidebar.slider("Score mínimo de match", 0, 100, 0, step=5)
fontes_disp  = ["Todas", "Gupy", "Greenhouse", "LinkedIn Posts", "Indeed"]
fonte_filtro = st.sidebar.selectbox("Filtrar por fonte", fontes_disp)

# ==========================================
# CABEÇALHO
# ==========================================
st.title("🤖 JobHunter AI — Painel de Controle")
st.caption("Monitoramento em tempo real da sua automação de caça a vagas.")

# ==========================================
# 2. LEITURA DO BANCO
# ==========================================
db_path = "vagas_enviadas.db"

if not os.path.exists(db_path):
    st.warning("⏳ Banco de dados ainda não foi criado. Aguarde a próxima execução.")
    st.stop()

conn = sqlite3.connect(db_path)

try:
    df = pd.read_sql_query("SELECT * FROM enviadas", conn)
except Exception as e:
    st.error(f"Erro ao ler o banco: {e}")
    conn.close()
    st.stop()

try:
    df_desc = pd.read_sql_query("SELECT * FROM descartadas", conn)
except Exception:
    df_desc = pd.DataFrame()

conn.close()

if df.empty:
    st.info("Banco pronto, mas nenhuma vaga inédita foi salva ainda.")
    st.stop()

# Normaliza
df['data_envio'] = pd.to_datetime(df['data_envio']) - pd.Timedelta(hours=3)
df['Data'] = df['data_envio'].dt.date

for col, fallback in [('match_score', 0), ('titulo', '—'), ('empresa', '—'), ('fonte', '—'), ('local', '—')]:
    if col not in df.columns:
        df[col] = fallback

df['match_score'] = pd.to_numeric(df['match_score'], errors='coerce').fillna(0).astype(int)

df_filtrado = df[df['match_score'] >= score_min].copy()
if fonte_filtro != "Todas":
    df_filtrado = df_filtrado[df_filtrado['fonte'] == fonte_filtro]

# ==========================================
# 3. KPIs
# ==========================================
st.subheader("📊 Resumo da Execução")

vagas_ouro     = (df_filtrado['match_score'] >= 85).sum()
score_medio    = int(df_filtrado['match_score'].mean()) if not df_filtrado.empty else 0
ultima_captura = df['data_envio'].max().strftime("%d/%m %H:%M") if not df.empty else "—"
total_desc     = len(df_desc) if not df_desc.empty else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("🔥 Vagas inéditas",    len(df))
c2.metric("🎯 Após filtros",      len(df_filtrado))
c3.metric("⭐ Score médio",       f"{score_medio}%")
c4.metric("🚨 Vagas ouro (≥85)", vagas_ouro)
c5.metric("🗃️ Descartadas",      total_desc)
c6.metric("⏱️ Última captura",   ultima_captura)

# Destaque visual se houver vagas ouro
if vagas_ouro > 0:
    st.error(f"🚨 **{vagas_ouro} vaga(s) OURO detectada(s) com score ≥ 85%!** Verifique o ranking abaixo.")

st.divider()

# ==========================================
# 4. TABELA COM FORMATAÇÃO CONDICIONAL
# ── ITEM 8: Botão de candidatura ─────────
# ==========================================
st.subheader("🏆 Ranking de Vagas")

if df_filtrado.empty:
    st.info("Nenhuma vaga encontrada com os filtros selecionados.")
else:
    def colorir_score(val):
        if val >= 85:   return 'background-color:#D4EDDA;color:#155724;font-weight:700;'
        elif val >= 50: return 'background-color:#FAEEDA;color:#854F0B;font-weight:600;'
        else:           return 'background-color:#FCEBEB;color:#A32D2D;font-weight:600;'

    def badge_status(val):
        if val >= 85:   return '🚨 Ouro'
        elif val >= 50: return '🥈 Prata'
        else:           return '🔴 Atenção'

    df_tabela = df_filtrado[['data_envio','titulo','empresa','fonte','local','match_score','link']].copy()
    df_tabela = df_tabela.sort_values('match_score', ascending=False).reset_index(drop=True)
    df_tabela['status'] = df_tabela['match_score'].apply(badge_status)

    # ── ITEM 8: Renderiza linha a linha com botão de candidatura ─────
    st.markdown("##### Clique em **Candidatar** para abrir a vaga diretamente")

    for _, row in df_tabela.iterrows():
        score  = row['match_score']
        titulo = str(row['titulo'])
        emp    = str(row['empresa'])
        local  = str(row['local'])
        fonte  = str(row['fonte'])
        link   = str(row['link'])
        status = badge_status(score)

        # Cor do container por score
        if score >= 85:
            border_color = "#28a745"
        elif score >= 50:
            border_color = "#fd7e14"
        else:
            border_color = "#dc3545"

        with st.container():
            st.markdown(f"""
            <div style="border-left: 4px solid {border_color}; padding: 8px 14px; margin-bottom: 8px; border-radius: 4px; background: #fafafa;">
                <b>{status} {titulo}</b><br>
                <span style="color:#555; font-size:13px;">🏢 {emp} &nbsp;|&nbsp; 📍 {local} &nbsp;|&nbsp; 🔖 {fonte} &nbsp;|&nbsp; ⭐ {score}%</span>
            </div>
            """, unsafe_allow_html=True)

            col_btn, col_link = st.columns([1, 5])
            with col_btn:
                st.link_button("👉 Candidatar", link, use_container_width=True)

st.divider()

# ==========================================
# 5. GRÁFICO DE ÁREA
# ==========================================
st.subheader("📈 Tendência do Mercado (Vagas por Dia)")

vagas_por_dia = df.groupby('Data').size().reset_index(name='Vagas')
vagas_por_dia['Data'] = pd.to_datetime(vagas_por_dia['Data'])
vagas_por_dia = vagas_por_dia.set_index('Data')

if not vagas_por_dia.empty:
    vagas_por_dia = vagas_por_dia.reindex(
        pd.date_range(vagas_por_dia.index.min(), vagas_por_dia.index.max(), freq='D'),
        fill_value=0
    )
    vagas_por_dia.index.name = 'Data'
    st.area_chart(vagas_por_dia, color="#378ADD")
else:
    st.info("Dados insuficientes para o gráfico.")

if df['match_score'].sum() > 0:
    score_por_dia = (
        df[df['match_score'] > 0]
        .groupby('Data')['match_score']
        .mean().round(1).reset_index()
    )
    score_por_dia.columns = ['Data', 'Score Médio']
    score_por_dia['Data'] = pd.to_datetime(score_por_dia['Data'])
    score_por_dia = score_por_dia.set_index('Data')
    st.caption("Score médio de aderência por dia")
    st.line_chart(score_por_dia, color="#639922")

st.divider()

# ==========================================
# 6. ABA DE DESCARTADAS
# ==========================================
if not df_desc.empty:
    with st.expander(f"🗃️ Vagas Descartadas ({len(df_desc)}) — clique para analisar"):
        st.caption("Vagas que não passaram no filtro. Use para ajustar os critérios.")

        motivos = df_desc['motivo'].value_counts().reset_index()
        motivos.columns = ['Motivo', 'Qtd']
        col_a, col_b = st.columns([1, 2])
        with col_a:
            st.dataframe(motivos, use_container_width=True, hide_index=True)
        with col_b:
            st.bar_chart(motivos.set_index('Motivo'), color="#E24B4A")

        df_desc_display = df_desc[['titulo','empresa','fonte','local','motivo']].copy()
        df_desc_display.columns = ['Cargo','Empresa','Fonte','Local','Motivo do Descarte']
        st.dataframe(df_desc_display, use_container_width=True, hide_index=True)

st.divider()

# ==========================================
# 7. HISTÓRICO COMPLETO
# ==========================================
with st.expander("🔗 Histórico completo de links enviados"):
    df_hist = df[['data_envio','link']].sort_values('data_envio', ascending=False).copy()
    df_hist['data_envio'] = df_hist['data_envio'].dt.strftime('%d/%m/%Y %H:%M')
    df_hist.columns = ['Data/Hora','Link']
    st.dataframe(df_hist, use_container_width=True, hide_index=True)
