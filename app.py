import streamlit as st
import sqlite3
import pandas as pd
import json
import os

st.set_page_config(page_title="JobHunter AI Pro", page_icon="📈", layout="wide")

# ==========================================
# 1. BARRA LATERAL (FILTROS E PERFIL)
# ==========================================
try:
    with open("fase3_perfil/perfil.json", "r", encoding="utf-8") as f:
        perfil = json.load(f)
    
    st.sidebar.header("👤 Perfil Ativo")
    st.sidebar.write(f"**Cargo:** {perfil.get('cargo_atual', 'N/A')}")
    
    # Filtro Dinâmico
    st.sidebar.divider()
    st.sidebar.subheader("🎛️ Filtros de Relevância")
    score_minimo = st.sidebar.slider("Aderência mínima (Match Score)", 0, 100, 50)
    
except:
    st.sidebar.warning("Perfil não carregado.")
    score_minimo = 0

# ==========================================
# 2. CARREGAMENTO E FILTRAGEM
# ==========================================
db_path = "vagas_enviadas.db"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM enviadas", conn)
    conn.close()

    if not df.empty:
        df['data_envio'] = pd.to_datetime(df['data_envio']) - pd.Timedelta(hours=3)
        # Nota: Certifique-se de que o seu robô está salvando 'match_score' no BD. 
        # Se não estiver, o filtro de score será aplicado apenas no que estiver na memória.
        
        # Filtro aplicado
        df_filtrado = df[df['match_score'] >= score_minimo] if 'match_score' in df.columns else df

        # ==========================================
        # 3. PAINEL DE MÉTRICAS (KPIs)
        # ==========================================
        col1, col2, col3 = st.columns(3)
        col1.metric("🔥 Vagas Totais", len(df))
        if 'match_score' in df.columns:
            col2.metric("🎯 Match Médio", f"{df['match_score'].mean():.1f}%")
        col3.metric("⏱️ Última Captura", df['data_envio'].max().strftime("%d/%m %H:%M"))

        st.divider()

        # ==========================================
        # 4. TABELA COLORIDA E GRÁFICO
        # ==========================================
        tab1, tab2 = st.tabs(["📊 Visão Geral", "🔗 Tabela Detalhada"])

        with tab1:
            st.subheader("📈 Tendência do Mercado")
            df['Data'] = df['data_envio'].dt.date
            tendencia = df.groupby('Data').size()
            st.area_chart(tendencia, color="#00cc96")

        with tab2:
            st.subheader("📋 Vagas Filtradas")
            st.dataframe(
                df_filtrado[['data_envio', 'titulo', 'empresa', 'match_score']].sort_values(by='match_score', ascending=False),
                column_config={
                    "match_score": st.column_config.ProgressColumn(
                        "Aderência",
                        help="Nível de compatibilidade com seu perfil",
                        format="%d%%",
                        min_value=0,
                        max_value=100,
                    ),
                },
                use_container_width=True,
                hide_index=True
            )
    else:
        st.info("Banco de dados vazio.")
else:
    st.warning("Aguardando automação rodar.")
