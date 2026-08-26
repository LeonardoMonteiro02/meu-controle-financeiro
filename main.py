from datetime import datetime, timedelta
import io
import warnings
from dateutil.relativedelta import relativedelta
import pandas as pd
import psycopg2
from reportlab.lib import colors

# Silenciar avisos do Pandas no terminal
warnings.filterwarnings("ignore", category=UserWarning)

# Importações do ReportLab para o PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st

# Configuração da página
st.set_page_config(
    page_title="Meu Controle Financeiro Pro", page_icon="💎", layout="wide"
)

# Customização estética
st.markdown(
    """
    <style>
        .stButton>button[kind="primary"] {
            background-color: #0066cc !important;
            border-color: #0066cc !important;
            color: white !important;
        }
        .stButton>button[kind="primary"]:hover {
            background-color: #0052a3 !important;
        }
        button[data-baseweb="tab"] p {
            font-size: 16px !important;
            font-weight: 500 !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            border-bottom-color: #0066cc !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] p {
            color: #0066cc !important;
        }

        .card-mes {
            background: #ffffff;
            border-radius: 14px;
            padding: 12px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
            text-align: center;
            margin-bottom: 8px;
        }
        .card-header-title {
            font-size: 18px;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 6px;
        }

        .metrics-container {
            display: flex;
            justify-content: space-between;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 6px 4px;
            margin-bottom: 8px;
            font-size: 11px;
            font-weight: 600;
        }
        .metric-box { flex: 1; text-align: center; }
        .metric-label { font-size: 10px; color: #64748b; margin-bottom: 2px; display: block; }
        .txt-in { color: #16a34a; }
        .txt-out { color: #dc2626; }
        .txt-saldo-pos { color: #15803d; font-weight: 700; }
        .txt-saldo-neg { color: #b91c1c; font-weight: 700; }

        .ciclo-block {
            background: #f8fafc;
            border: 1px solid #f1f5f9;
            border-radius: 8px;
            padding: 6px 8px;
            margin-bottom: 6px;
            text-align: left;
        }
        .ciclo-head { font-size: 11px; font-weight: 700; color: #334155; margin-bottom: 4px; display: flex; justify-content: space-between; }
        .ciclo-row { display: flex; justify-content: space-between; font-size: 11px; font-weight: 600; }
        .val-pago { color: #16a34a; }
        .val-pend { color: #dc2626; }

        .cartao-container { display: flex; gap: 4px; margin-top: 6px; }
        .cartao-badge { flex: 1; font-size: 10px; background: #f1f5f9; color: #475569; border-radius: 6px; padding: 4px 2px; border: 1px dashed #cbd5e1; font-weight: 500; }
        .card-invest { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 10px; box-shadow: 1px 1px 5px rgba(0,0,0,0.02); margin-bottom: 10px; }
    </style>
""",
    unsafe_allow_html=True,
)

TAXA_CDI_ANUAL_PADRAO = 14.40

LISTA_CATEGORIAS_ENTRADA = [
    "💰 Salário Base / Pró-labore",
    "🍔 Vale Alimentação / Refeição",
    "✨ Renda Extra / Freelance",
    "🎁 Bônus / Premiações",
    "🎄 13º Salário / Férias",
    "📦 Venda de Bens / Desapegos",
    "💫 Presentes / Reembolsos",
    "✨ Outros",
]

LISTA_CATEGORIAS_SAIDA = [
    "🏠 Moradia (Aluguel/Condomínio)",
    "🛒 Mercado & Alimentação",
    "⚡ Contas Fixas (Luz/Água/Internet)",
    "🚗 Transporte & Combustível",
    "💊 Saúde & Farmácia",
    "🎭 Lazer & Viagens",
    "🛍️ Compras & Vestuário",
    "📉 Dívidas & Empréstimos",
    "🏦 Investimentos Aplicados",
    "✨ Outros",
]

LISTA_FORMAS_PAGAMENTO = [
    "⚡ Pix",
    "💳 Cartão de Crédito Rhuan",
    "💳 Cartão de Crédito Filipe",
    "💳 Cartão de Débito",
    "💵 Dinheiro",
    "🔄 Débito Automático",
]

CICLO_DIA_20 = "🗓️ Ciclo Dia 20 (40% Salário - Adiantamentos)"
CICLO_5_DIA_UTIL = "🗓️ Ciclo 5º Dia Útil (60% Salário - Cartão/Serviços)"
LISTA_CICLOS = [CICLO_DIA_20, CICLO_5_DIA_UTIL]


# --- REGRA DE COMPETÊNCIA FINANCEIRA (DO DIA 20 AO DIA 19) ---
def calcular_mes_competencia(data_dt):
    if data_dt.day >= 20:
        data_competencia = data_dt + relativedelta(months=1)
    else:
        data_competencia = data_dt
    return data_competencia.strftime("%m/%Y")


def determinar_ciclo_automatico(data_dt):
    if data_dt.day >= 16:
        return CICLO_DIA_20
    else:
        return CICLO_5_DIA_UTIL


def atualizar_ciclo_entrada():
    st.session_state.ciclo_in = determinar_ciclo_automatico(
        st.session_state.date_in
    )


def atualizar_ciclo_saida():
    st.session_state.ciclo_out = determinar_ciclo_automatico(
        st.session_state.date_out
    )


def reclassificar_banco_existente(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, data FROM transacoes")
    registros = cursor.fetchall()

    for id_reg, data_str in registros:
        try:
            d_obj = datetime.strptime(data_str, "%d/%m/%Y")
            ciclo_correto = determinar_ciclo_automatico(d_obj)
            cursor.execute(
                "UPDATE transacoes SET ciclo = %s WHERE id = %s",
                (ciclo_correto, id_reg),
            )
        except Exception:
            pass
    conn.commit()
    cursor.close()


def conectar_db():
    db_url = st.secrets["postgres"]["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transacoes (
            id SERIAL PRIMARY KEY,
            data TEXT,
            tipo TEXT,
            recorrencia TEXT,
            categoria TEXT,
            descricao TEXT,
            forma_pagamento TEXT,
            valor DOUBLE PRECISION,
            pago INTEGER DEFAULT 0,
            ciclo TEXT DEFAULT '🗓️ Ciclo Dia 20 (40% Salário - Adiantamentos)'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS carteiras_investimento (
            id SERIAL PRIMARY KEY,
            nome_carteira TEXT,
            data_aplicacao TEXT,
            data_vencimento TEXT,
            porcentagem_cdi DOUBLE PRECISION,
            valor_aplicado DOUBLE PRECISION
        )
    """)
    conn.commit()
    cursor.close()

    return conn


def salvar_no_db(
    data_str,
    tipo,
    recorrencia,
    categoria,
    descricao,
    forma,
    valor,
    pago=0,
    ciclo=CICLO_DIA_20,
):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO transacoes (data, tipo, recorrencia, categoria, descricao, forma_pagamento, valor, pago, ciclo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """,
        (
            data_str,
            tipo,
            recorrencia,
            categoria,
            descricao,
            forma,
            valor,
            pago,
            ciclo,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()


def alternar_status_pago(id_registro, status_pago):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE transacoes SET pago = %s WHERE id = %s",
        (1 if status_pago else 0, id_registro),
    )
    conn.commit()
    cursor.close()
    conn.close()


def salvar_carteira_db(nome, data_ap, data_ven, pct_cdi, valor):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO carteiras_investimento (nome_carteira, data_aplicacao, data_vencimento, porcentagem_cdi, valor_aplicado)
        VALUES (%s, %s, %s, %s, %s)
    """,
        (nome, data_ap, data_ven, pct_cdi, valor),
    )
    conn.commit()
    cursor.close()
    conn.close()


def carregar_dados():
    db_url = st.secrets["postgres"]["DATABASE_URL"]
    try:
        df = pd.read_sql_query(
            "SELECT id, data, tipo, recorrencia, categoria, descricao,"
            " forma_pagamento, valor, pago, ciclo FROM transacoes",
            db_url,
        )
    except Exception:
        conn = conectar_db()
        df = pd.read_sql_query(
            "SELECT id, data, tipo, recorrencia, categoria, descricao,"
            " forma_pagamento, valor, pago, ciclo FROM transacoes",
            conn,
        )
        conn.close()

    if not df.empty:
        df.columns = [
            "ID",
            "Data",
            "Tipo",
            "Classificação",
            "Categoria",
            "Descrição",
            "Forma de Pagamento",
            "Valor",
            "Pago",
            "Ciclo de Caixa",
        ]
        df["Pago"] = df["Pago"].fillna(0).astype(int)
        df["Ciclo de Caixa"] = df["Ciclo de Caixa"].fillna(CICLO_DIA_20)
    return df


def carregar_carteiras():
    db_url = st.secrets["postgres"]["DATABASE_URL"]
    try:
        df = pd.read_sql_query(
            "SELECT id, nome_carteira, data_aplicacao, data_vencimento,"
            " porcentagem_cdi, valor_aplicado FROM carteiras_investimento",
            db_url,
        )
    except Exception:
        conn = conectar_db()
        df = pd.read_sql_query(
            "SELECT id, nome_carteira, data_aplicacao, data_vencimento,"
            " porcentagem_cdi, valor_aplicado FROM carteiras_investimento",
            conn,
        )
        conn.close()
    return df


def atualizar_linha_completa_db(
    id_registro,
    data,
    recorrencia,
    categoria,
    descricao,
    forma,
    valor,
    pago,
    ciclo,
):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE transacoes 
        SET data = %s, recorrencia = %s, categoria = %s, descricao = %s, forma_pagamento = %s, valor = %s, pago = %s, ciclo = %s
        WHERE id = %s
    """,
        (
            data,
            recorrencia,
            categoria,
            descricao,
            forma,
            valor,
            1 if pago else 0,
            ciclo,
            id_registro,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()


def deletar_linha_db(id_registro):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transacoes WHERE id = %s", (id_registro,))
    conn.commit()
    cursor.close()
    conn.close()


def deletar_carteira_db(id_carteira):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM carteiras_investimento WHERE id = %s", (id_carteira,)
    )
    conn.commit()
    cursor.close()
    conn.close()


def deletar_tudo():
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE transacoes RESTART IDENTITY;")
    cursor.execute("TRUNCATE TABLE carteiras_investimento RESTART IDENTITY;")
    conn.commit()
    cursor.close()
    conn.close()


def calcular_dias_uteis(data_ini, data_fim):
    dias_uteis = 0
    data_corrente = data_ini
    while data_corrente <= data_fim:
        if data_corrente.weekday() < 5:
            dias_uteis += 1
        data_corrente += timedelta(days=1)
    return dias_uteis


def calcular_aliquota_iof(dias_corridos):
    if dias_corridos <= 0:
        return 0.96
    if dias_corridos >= 30:
        return 0.0
    aliquota = 0.96 - ((dias_corridos - 1) * 0.03)
    return max(0.0, aliquota)


def gerar_pdf_relatorio(
    dataframe, total_in, total_out, saldo_periodo, d_inicio, d_fim
):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0066cc"),
        alignment=1,
        spaceAfter=15,
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#555555"),
        alignment=1,
        spaceAfter=25,
    )
    h2_style = ParagraphStyle(
        "H2Style",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=15,
        spaceAfter=10,
    )
    text_style = ParagraphStyle(
        "TextStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#1e293b"),
    )
    header_table_style = ParagraphStyle(
        "HeaderTableStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=12,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    story.append(
        Paragraph("Relatorio de Controle Financeiro Pessoal", title_style)
    )
    story.append(
        Paragraph(
            f"Periodo consultado: {d_inicio.strftime('%d/%m/%Y')} ate"
            f" {d_fim.strftime('%d/%m/%Y')} | Gerado em:"
            f" {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            subtitle_style,
        )
    )

    story.append(Paragraph("Resumo Consolidado", h2_style))
    dados_resumo = [
        [
            Paragraph("<b>Indicador Financeiro</b>", text_style),
            Paragraph("<b>Valor (R$)</b>", text_style),
        ],
        [
            Paragraph("(+) Total de Receitas", text_style),
            Paragraph(
                f"R$ {total_in:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", "."),
                text_style,
            ),
        ],
        [
            Paragraph("(-) Total de Despesas / Dividas", text_style),
            Paragraph(
                f"R$ {total_out:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", "."),
                text_style,
            ),
        ],
        [
            Paragraph("(=) Saldo Liquido Final", text_style),
            Paragraph(
                f"<b>R$ {saldo_periodo:,.2f}</b>".replace(",", "X")
                .replace(".", ",")
                .replace("X", "."),
                text_style,
            ),
        ],
    ]
    t_resumo = Table(dados_resumo, colWidths=[200, 150])
    t_resumo.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#e2e8f0")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            (
                "BACKGROUND",
                (0, 3),
                (1, 3),
                (
                    colors.HexColor("#f0fdf4")
                    if saldo_periodo >= 0
                    else colors.HexColor("#fef2f2")
                ),
            ),
        ])
    )
    story.append(t_resumo)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Extrato Analitico de Lancamentos", h2_style))

    dados_lancamentos = [[
        Paragraph("Data", header_table_style),
        Paragraph("Status", header_table_style),
        Paragraph("Categoria", header_table_style),
        Paragraph("Descricao", header_table_style),
        Paragraph("Forma", header_table_style),
        Paragraph("Valor", header_table_style),
    ]]

    for _, r in dataframe.iterrows():
        categoria_limpa = str(r["Categoria"])
        for emoji in [
            "💰 ",
            "🍔 ",
            "✨ ",
            "🎁 ",
            "🎄 ",
            "📦 ",
            "💫 ",
            "🏠 ",
            "🛒 ",
            "⚡ ",
            "🚗 ",
            "💊 ",
            "🎭 ",
            "🛍 ",
            "🛍️ ",
            "📉 ",
            "🏦 ",
        ]:
            categoria_limpa = categoria_limpa.replace(emoji, "")

        status_txt = "Pago" if r["Pago"] == 1 else "Pendente"
        forma_limpa = (
            str(r["Forma de Pagamento"])
            .replace("⚡ ", "")
            .replace("💳 ", "")
            .replace("💵 ", "")
            .replace("🔄 ", "")
        )

        dados_lancamentos.append([
            Paragraph(str(r["Data"]), text_style),
            Paragraph(status_txt, text_style),
            Paragraph(categoria_limpa, text_style),
            Paragraph(
                str(r["Descrição"]) if r["Descrição"] else "-", text_style
            ),
            Paragraph(forma_limpa, text_style),
            Paragraph(
                f"R$ {r['Valor']:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", "."),
                text_style,
            ),
        ])

    t_lancamentos = Table(
        dados_lancamentos, colWidths=[65, 50, 110, 120, 110, 70]
    )
    t_lancamentos.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0066cc")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#f8fafc")],
            ),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(t_lancamentos)

    doc.build(story)
    buffer.seek(0)
    return buffer


conectar_db()

# --- HEADER DO SISTEMA ---
st.markdown(
    "<h1 style='text-align: center; color: #0066cc;'>💎 Meu Controle"
    " Financeiro Pro</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align: center; color: #555555;'>Mês Financeiro do Dia 20 ao"
    " Dia 19 com Checklist de Pagamentos e Férias.</p>",
    unsafe_allow_html=True,
)

c_sec1, c_sec2 = st.columns([3, 1])
with c_sec2:
    if st.button("🔄 Recalcular Ciclos do Banco", use_container_width=True):
        conn = conectar_db()
        reclassificar_banco_existente(conn)
        conn.close()
        st.success("Histórico corrigido!")
        st.rerun()

st.markdown("---")

(
    tab_entrada,
    tab_saida,
    tab_ferias,
    tab_geral,
    tab_ludica,
    tab_investimentos,
) = st.tabs([
    "📥 Lançar Receitas",
    "📤 Lançar Despesas",
    "🏖️ Planejar Férias",
    "📊 Painel Geral",
    "🎯 Cards por Mês e Ciclos",
    "📈 Carteiras CDI",
])

# --- ABA DE ENTRADAS ---
with tab_entrada:
    st.subheader("📥 Registro de Receitas")

    if "date_in" not in st.session_state:
        st.session_state.date_in = datetime.now()
    if "ciclo_in" not in st.session_state:
        st.session_state.ciclo_in = determinar_ciclo_automatico(
            st.session_state.date_in
        )

    col1, col2 = st.columns(2)
    with col1:
        data_in = st.date_input(
            "🗓️ Data do Recebimento",
            key="date_in",
            on_change=atualizar_ciclo_entrada,
        )
        categoria_in = st.selectbox(
            "📂 Origem do Recurso", LISTA_CATEGORIAS_ENTRADA, key="cat_in"
        )
        ciclo_in = st.selectbox(
            "📌 Ciclo (Atribuído Dinamicamente):",
            LISTA_CICLOS,
            key="ciclo_in",
        )
    with col2:
        valor_in = st.number_input(
            "💵 Valor Recebido (R$)", min_value=0.0, step=0.01, key="val_in"
        )
        forma_in = st.selectbox(
            "💳 Meio de Recebimento",
            ["⚡ Pix", "🏦 Transferência", "💵 Dinheiro"],
            key="form_in",
        )
        pago_in = st.checkbox(
            "✅ Receita já caiu na conta?", value=True, key="pago_in"
        )

    descricao_in = st.text_area(
        "✍️ Notas Adicionais / Detalhes",
        placeholder="Ex: 40% do salário recebido no dia 20",
        key="desc_in",
    )
    submit_in = st.button(
        "Gravar Entrada ✅", use_container_width=True, type="primary"
    )

    if submit_in:
        if valor_in > 0:
            salvar_no_db(
                data_in.strftime("%d/%m/%Y"),
                "📥 Entrada",
                "Fixa",
                categoria_in,
                descricao_in,
                forma_in,
                valor_in,
                1 if pago_in else 0,
                ciclo_in,
            )
            st.success("Receita adicionada com sucesso!")
            st.rerun()

# --- ABA DE SAÍDAS ---
with tab_saida:
    st.subheader("📤 Registro de Despesas e Compras Parceladas")

    if "date_out" not in st.session_state:
        st.session_state.date_out = datetime.now()
    if "ciclo_out" not in st.session_state:
        st.session_state.ciclo_out = determinar_ciclo_automatico(
            st.session_state.date_out
        )
    if "eh_parcelado" not in st.session_state:
        st.session_state.eh_parcelado = False

    col1, col2 = st.columns(2)
    with col1:
        data_out = st.date_input(
            "🗓️ Data do Pagamento (ou da 1ª Parcela)",
            key="date_out",
            on_change=atualizar_ciclo_saida,
        )
        categoria_out = st.selectbox(
            "📂 Categoria da Despesa", LISTA_CATEGORIAS_SAIDA, key="cat_out"
        )

        ciclo_out = st.selectbox(
            "📌 Ciclo de Pagamento (Atribuído Dinamicamente):",
            LISTA_CICLOS,
            key="ciclo_out",
        )

        eh_parcelado = st.checkbox(
            "💳 Esta compra é parcelada?",
            value=st.session_state.eh_parcelado,
            key="check_parc",
        )

        if eh_parcelado:
            recorrencia = "Variável"
        else:
            recorrencia = st.radio(
                "🔍 Classificação do Gasto:",
                ["Variável", "Fixa"],
                help="Gasto Fixo se repetirá pelos próximos 12 meses.",
            )

    with col2:
        valor_out = st.number_input(
            "💵 Valor por parcela (ou valor total se à vista)",
            min_value=0.0,
            step=0.01,
            key="val_out",
        )

        if eh_parcelado:
            forma_out = st.selectbox(
                "💳 Escolha o Cartão de Crédito:",
                [
                    "💳 Cartão de Crédito Rhuan",
                    "💳 Cartão de Crédito Filipe",
                ],
                key="form_out_credito",
            )
        else:
            forma_out = st.selectbox(
                "💳 Meio de Pagamento", LISTA_FORMAS_PAGAMENTO, key="form_out"
            )

        num_parcelas = st.number_input(
            "Número de Parcelas:",
            min_value=2,
            max_value=48,
            value=2,
            step=1,
            disabled=not eh_parcelado,
        )

        ja_pago_saida = st.checkbox(
            "✅ Já foi pago / debitado?", value=False, key="pago_out"
        )

    descricao_out = st.text_area(
        "✍️ Notas Adicionais / Detalhes",
        placeholder="Ex: Aluguel adiantado para vencimento do mês que vem",
        key="desc_out",
    )
    submit_out = st.button(
        "Gravar Despesa ❌", use_container_width=True, type="primary"
    )

    if submit_out:
        if valor_out > 0:
            if eh_parcelado:
                for i in range(num_parcelas):
                    date_parcela = data_out + relativedelta(months=i)
                    ciclo_parc = determinar_ciclo_automatico(date_parcela)
                    desc_parcela = (
                        f"{descricao_out} (Parc. {i + 1}/{num_parcelas})"
                        if descricao_out
                        else f"Compra Parcelada ({i + 1}/{num_parcelas})"
                    )
                    salvar_no_db(
                        date_parcela.strftime("%d/%m/%Y"),
                        "📤 Saída",
                        "Variável (Parcelada)",
                        categoria_out,
                        desc_parcela,
                        forma_out,
                        valor_out,
                        1 if (i == 0 and ja_pago_saida) else 0,
                        ciclo_parc,
                    )
                st.success(
                    f"Compra parcelada em {num_parcelas}x registrada com ciclos"
                    " calculados!"
                )
            elif recorrencia == "Fixa":
                for i in range(12):
                    date_fixa = data_out + relativedelta(months=i)
                    ciclo_fixa = determinar_ciclo_automatico(date_fixa)
                    desc_fixa = (
                        f"{descricao_out} (Mensal Fixa)"
                        if descricao_out
                        else "Conta Fixa Recorrente"
                    )
                    salvar_no_db(
                        date_fixa.strftime("%d/%m/%Y"),
                        "📤 Saída",
                        "Fixa",
                        categoria_out,
                        desc_fixa,
                        forma_out,
                        valor_out,
                        1 if (i == 0 and ja_pago_saida) else 0,
                        ciclo_fixa,
                    )
                st.success("Conta fixa projetada para os próximos 12 meses!")
            else:
                salvar_no_db(
                    data_out.strftime("%d/%m/%Y"),
                    "📤 Saída",
                    recorrencia,
                    categoria_out,
                    descricao_out,
                    forma_out,
                    valor_out,
                    1 if ja_pago_saida else 0,
                    ciclo_out,
                )
                st.success("Despesa registrada com sucesso!")
            st.rerun()

# --- ABA: PLANEJADOR DE FÉRIAS ---
with tab_ferias:
    st.subheader("🏖️ Calculadora e Lançador Automático de Férias")
    st.info(
        "📌 **Regra de Férias:** O valor antecipado é fatiado em **40% (Ciclo"
        " Dia 20)** e **60% (Ciclo 5º Dia Útil)** do mês seguinte para manter"
        " seus dois ciclos abastecidos na volta das férias. O **1/3 Adicional"
        " Líquido** é o seu bônus livre!"
    )

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        salario_bruto = st.number_input(
            "💵 Seu Salário Bruto Mensal (R$):",
            min_value=0.0,
            value=4714.00,
            step=100.0,
            key="f_sal_bruto",
        )
        dias_ferias = st.selectbox(
            "🗓️ Quantidade de Dias de Férias:",
            [15, 20, 30],
            index=0,
            key="f_dias",
        )
        data_inicio_ferias = st.date_input(
            "✈️ Data de Início das Férias:", datetime.now(), key="f_data_ini"
        )
        pct_descontos = (
            st.slider(
                "📉 Porcentagem Estimada de Descontos (INSS/IRRF %):",
                min_value=0.0,
                max_value=25.0,
                value=12.0,
                step=0.5,
                key="f_pct_desc",
            )
            / 100.0
        )

    # CÁLCULOS FINANCEIROS
    data_pagamento_ferias = data_inicio_ferias - timedelta(days=2)
    valor_dias_ferias_bruto = (salario_bruto / 30.0) * dias_ferias
    valor_terco_bruto = valor_dias_ferias_bruto / 3.0

    salario_antecipado_liquido = valor_dias_ferias_bruto * (1.0 - pct_descontos)
    terco_liquido = valor_terco_bruto * (1.0 - pct_descontos)
    total_receber_ferias = salario_antecipado_liquido + terco_liquido

    reserva_40 = salario_antecipado_liquido * 0.40
    reserva_60 = salario_antecipado_liquido * 0.60

    mes_competencia_reserva = calcular_mes_competencia(
        data_inicio_ferias + timedelta(days=15)
    )

    with f_col2:
        with st.container(border=True):
            st.markdown("#### 📊 Resumo do Pagamento de Férias")
            st.caption(
                "Data do Crédito na Conta:"
                f" **{data_pagamento_ferias.strftime('%d/%m/%Y')}**"
            )
            st.divider()

            st.markdown(
                "🔒 **SALÁRIO ANTECIPADO (FATIADO PARA O MÊS"
                f" {mes_competencia_reserva}):**"
            )
            st.markdown(
                f"- **40% Reserva Dia 20:** R$ {reserva_40:,.2f}"
                " *(Aluguel/Luz/Net)*"
            )
            st.markdown(
                f"- **60% Reserva 5º Dia Útil:** R$ {reserva_60:,.2f}"
                " *(Cartão/Serviços)*"
            )
            st.caption(
                "⚠️ Esses dois valores cobrirão as contas na volta das férias."
            )

            st.divider()

            st.metric(
                label="🎁 1/3 CONSTITUCIONAL LÍQUIDO (BÔNUS LIVRE)",
                value=f"R$ {terco_liquido:,.2f}",
                delta="Dinheiro Livre para Lazer / Viagens",
                delta_color="normal",
            )

            st.divider()
            st.markdown(
                f"### 💰 Total a Receber: **R$ {total_receber_ferias:,.2f}**"
            )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(
        "🚀 Gravar Lançamentos de Férias no Sistema",
        type="primary",
        use_container_width=True,
        key="btn_gravar_ferias",
    ):
        salvar_no_db(
            data_pagamento_ferias.strftime("%d/%m/%Y"),
            "📥 Entrada",
            "Variável",
            "🎄 13º Salário / Férias",
            f"1/3 de Férias ({dias_ferias} dias) - Bônus Livre",
            "⚡ Pix",
            terco_liquido,
            1,
            determinar_ciclo_automatico(data_pagamento_ferias),
        )

        data_reserva_dia20 = data_inicio_ferias.replace(day=20)

        salvar_no_db(
            data_reserva_dia20.strftime("%d/%m/%Y"),
            "📥 Entrada",
            "Fixa",
            "💰 Salário Base / Pró-labore",
            (
                f"Reserva 40% Antecipação Férias ({dias_ferias} dias) para"
                " Adiantamentos"
            ),
            "⚡ Pix",
            reserva_40,
            1,
            CICLO_DIA_20,
        )

        data_reserva_5dia = (data_inicio_ferias + relativedelta(months=1)).replace(
            day=5
        )

        salvar_no_db(
            data_reserva_5dia.strftime("%d/%m/%Y"),
            "📥 Entrada",
            "Fixa",
            "💰 Salário Base / Pró-labore",
            (
                f"Reserva 60% Antecipação Férias ({dias_ferias} dias) para"
                " Cartões/Serviços"
            ),
            "⚡ Pix",
            reserva_60,
            1,
            CICLO_5_DIA_UTIL,
        )

        st.success(
            "Férias gravadas! O 1/3 caiu no Mês 09 (Bônus), os 40% no dia 20/09"
            " e os 60% no dia 05/10."
        )
        st.rerun()

# --- ABA DE VISÃO GERAL / PAINEL GERAL ---
with tab_geral:
    df_bruto = carregar_dados()
    if not df_bruto.empty:
        st.subheader("🔍 Filtros Gerais")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            data_inicio = st.date_input(
                "📅 Data Inicial:", datetime.now().date().replace(day=1)
            )
        with col_f2:
            data_fim = st.date_input(
                "📅 Data Final:",
                (datetime.now() + relativedelta(months=3)).date(),
            )

        df_bruto["Data_Obj"] = pd.to_datetime(
            df_bruto["Data"], format="%d/%m/%Y"
        )
        df = df_bruto[
            (df_bruto["Data_Obj"] >= pd.Timestamp(data_inicio))
            & (df_bruto["Data_Obj"] <= pd.Timestamp(data_fim))
        ].copy()
        df.sort_values(by="Data_Obj", inplace=True)
        df.drop(columns=["Data_Obj"], inplace=True)

        t_in = df[df["Tipo"].str.contains("Entrada")]["Valor"].sum()
        t_out = df[df["Tipo"].str.contains("Saída")]["Valor"].sum()
        saldo = t_in - t_out

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Total Receitas",
            f"R$ {t_in:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )
        c2.metric(
            "Total Despesas",
            f"R$ {t_out:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )
        c3.metric(
            "Saldo do Período",
            f"R$ {saldo:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
            delta=f"R$ {saldo:,.2f}",
            delta_color="normal" if saldo >= 0 else "inverse",
        )

        st.markdown("<br>", unsafe_allow_html=True)

        col_tabela, col_modificacao = st.columns([1.6, 1.4])
        with col_tabela:
            df_exibir = df.copy()
            df_exibir["Pago"] = df_exibir["Pago"].map(
                {1: "✅ Pago", 0: "⏳ Pendente"}
            )
            st.dataframe(df_exibir, use_container_width=True, hide_index=True)

            pdf_data = gerar_pdf_relatorio(
                df, t_in, t_out, saldo, data_inicio, data_fim
            )
            st.download_button(
                label="📥 Baixar Relatório do Período em PDF",
                data=pdf_data,
                file_name=(
                    f"relatorio_financeiro_{data_inicio.strftime('%d%m%Y')}_a_{data_fim.strftime('%d%m%Y')}.pdf"
                ),
                mime="application/pdf",
                use_container_width=True,
            )

            with st.expander("🚨 Resetar Todo o Sistema"):
                if st.button(
                    "🗑️ Apagar Histórico Completo", use_container_width=True
                ):
                    deletar_tudo()
                    st.rerun()

        with col_modificacao:
            with st.container(border=True):
                st.subheader("🛠️ Ajuste Rápido / Edição Completa")
                opcoes_itens = [
                    f"ID: {r['ID']} | {r['Data']} - {r['Categoria']} - R$"
                    f" {r['Valor']:.2f}"
                    for _, r in df.iterrows()
                ]
                item_sel = st.selectbox(
                    "Escolha um item para Modificar ou Excluir:",
                    [""] + opcoes_itens,
                )

                if item_sel:
                    id_sel = int(item_sel.split(" | ")[0].replace("ID: ", ""))
                    dados_linha = df[df["ID"] == id_sel].iloc[0]

                    st.markdown("---")
                    ed_data = st.date_input(
                        "📅 Alterar Data:",
                        datetime.strptime(dados_linha["Data"], "%d/%m/%Y"),
                    )
                    ed_class = st.selectbox(
                        "🔍 Classificação:",
                        ["Variável", "Fixa", "Variável (Parcelada)"],
                        index=[
                            "Variável",
                            "Fixa",
                            "Variável (Parcelada)",
                        ].index(dados_linha["Classificação"])
                        if dados_linha["Classificação"]
                        in ["Variável", "Fixa", "Variável (Parcelada)"]
                        else 0,
                    )

                    lista_cat_dinamica = (
                        LISTA_CATEGORIAS_ENTRADA
                        if "Entrada" in dados_linha["Tipo"]
                        else LISTA_CATEGORIAS_SAIDA
                    )
                    idx_cat = (
                        lista_cat_dinamica.index(dados_linha["Categoria"])
                        if dados_linha["Categoria"] in lista_cat_dinamica
                        else 0
                    )
                    ed_cat = st.selectbox(
                        "📂 Categoria:", lista_cat_dinamica, index=idx_cat
                    )

                    ed_val = st.number_input(
                        "💵 Valor (R$):",
                        min_value=0.0,
                        value=float(dados_linha["Valor"]),
                        step=0.01,
                    )
                    ed_desc = st.text_area(
                        "✍️ Descrição:", value=str(dados_linha["Descrição"])
                    )
                    ed_forma = st.selectbox(
                        "💳 Meio de Pagamento:",
                        LISTA_FORMAS_PAGAMENTO,
                        index=LISTA_FORMAS_PAGAMENTO.index(
                            dados_linha["Forma de Pagamento"]
                        )
                        if dados_linha["Forma de Pagamento"]
                        in LISTA_FORMAS_PAGAMENTO
                        else 0,
                    )
                    ed_ciclo = st.selectbox(
                        "📌 Ciclo:",
                        LISTA_CICLOS,
                        index=LISTA_CICLOS.index(dados_linha["Ciclo de Caixa"])
                        if dados_linha["Ciclo de Caixa"] in LISTA_CICLOS
                        else 0,
                    )
                    ed_pago = st.checkbox(
                        "✅ Marcado como Pago?",
                        value=bool(dados_linha["Pago"]),
                    )

                    c_btn1, c_btn2 = st.columns(2)
                    with c_btn1:
                        if st.button(
                            "💾 Salvar Alterações",
                            use_container_width=True,
                            type="primary",
                        ):
                            atualizar_linha_completa_db(
                                id_sel,
                                ed_data.strftime("%d/%m/%Y"),
                                ed_class,
                                ed_cat,
                                ed_desc,
                                ed_forma,
                                ed_val,
                                ed_pago,
                                ed_ciclo,
                            )
                            st.success("Lançamento atualizado!")
                            st.rerun()
                    with c_btn2:
                        if st.button("🗑️ Excluir Item", use_container_width=True):
                            deletar_linha_db(id_sel)
                            st.success("Lançamento apagado!")
                            st.rerun()

# --- ABA LÚDICA: CARDS POR MÊS E CHECKLIST INTERATIVO COM PERÍODO ---
with tab_ludica:
    st.subheader(
        "🎯 Painel por Mês Financeiro: Entradas, Saídas e Ciclos de Pagamento"
    )
    df_ludico = carregar_dados()

    if not df_ludico.empty:
        df_ludico["Data_Obj"] = pd.to_datetime(
            df_ludico["Data"], format="%d/%m/%Y"
        )
        df_ludico["Mês_Financeiro"] = df_ludico["Data_Obj"].apply(
            calcular_mes_competencia
        )

        lista_meses = sorted(
            list(df_ludico["Mês_Financeiro"].unique()),
            key=lambda x: datetime.strptime(x, "%m/%Y"),
        )

        cols_cards = st.columns(
            len(lista_meses) if len(lista_meses) <= 6 else 6
        )
        if "mes_ativo" not in st.session_state:
            st.session_state.mes_ativo = lista_meses[0]

        for idx, m in enumerate(lista_meses):
            df_m = df_ludico[df_ludico["Mês_Financeiro"] == m]

            dt_mes = datetime.strptime(m, "%m/%Y")
            dt_inicio_periodo = (dt_mes - relativedelta(months=1)).replace(day=20)
            dt_fim_periodo = dt_mes.replace(day=19)
            texto_periodo = f"({dt_inicio_periodo.strftime('%d/%m')} a {dt_fim_periodo.strftime('%d/%m')})"

            ent_m = df_m[df_m["Tipo"].str.contains("Entrada")]["Valor"].sum()
            sai_m = df_m[df_m["Tipo"].str.contains("Saída")]["Valor"].sum()
            saldo_m = ent_m - sai_m

            df_c1 = df_m[df_m["Ciclo de Caixa"].str.contains("Dia 20")]
            c1_in_pago = df_c1[(df_c1["Tipo"].str.contains("Entrada")) & (df_c1["Pago"] == 1)]["Valor"].sum()
            c1_in_pend = df_c1[(df_c1["Tipo"].str.contains("Entrada")) & (df_c1["Pago"] == 0)]["Valor"].sum()
            c1_out_pago = df_c1[(df_c1["Tipo"].str.contains("Saída")) & (df_c1["Pago"] == 1)]["Valor"].sum()
            c1_out_pend = df_c1[(df_c1["Tipo"].str.contains("Saída")) & (df_c1["Pago"] == 0)]["Valor"].sum()

            df_c2 = df_m[df_m["Ciclo de Caixa"].str.contains("5º Dia Útil")]
            c2_in_pago = df_c2[(df_c2["Tipo"].str.contains("Entrada")) & (df_c2["Pago"] == 1)]["Valor"].sum()
            c2_in_pend = df_c2[(df_c2["Tipo"].str.contains("Entrada")) & (df_c2["Pago"] == 0)]["Valor"].sum()
            c2_out_pago = df_c2[(df_c2["Tipo"].str.contains("Saída")) & (df_c2["Pago"] == 1)]["Valor"].sum()
            c2_out_pend = df_c2[(df_c2["Tipo"].str.contains("Saída")) & (df_c2["Pago"] == 0)]["Valor"].sum()

            fatura_rhuan = df_m[df_m["Forma de Pagamento"] == "💳 Cartão de Crédito Rhuan"]["Valor"].sum()
            fatura_filipe = df_m[df_m["Forma de Pagamento"] == "💳 Cartão de Crédito Filipe"]["Valor"].sum()

            txt_saldo_class = "txt-saldo-pos" if saldo_m >= 0 else "txt-saldo-neg"

            html_content = (
                f"<div class='card-mes'>"
                f"<div class='card-header-title'>Mês {m}</div>"
                f"<div style='font-size:11px; font-weight:600; color:#64748b; margin-top:-4px; margin-bottom:8px;'>{texto_periodo}</div>"
                f"<div class='metrics-container'>"
                f"<div class='metric-box'><span class='metric-label'>Entrou</span><span class='txt-in'>+ R$ {ent_m:,.2f}</span></div>"
                f"<div class='metric-box'><span class='metric-label'>Saiu</span><span class='txt-out'>- R$ {sai_m:,.2f}</span></div>"
                f"<div class='metric-box'><span class='metric-label'>Saldo</span><span class='{txt_saldo_class}'>R$ {saldo_m:,.2f}</span></div>"
                f"</div>"

                f"<div class='ciclo-block'>"
                f"<div class='ciclo-head'><span>🗓️ Ciclo Dia 20</span></div>"
                f"<div class='ciclo-row' style='margin-bottom:2px;'>"
                f"<span class='val-pago'>📥 Rec: R$ {c1_in_pago:,.2f}</span>"
                f"<span class='val-pend'>A Rec: R$ {c1_in_pend:,.2f}</span>"
                f"</div>"
                f"<div class='ciclo-row'>"
                f"<span class='val-pago'>📤 Pago: R$ {c1_out_pago:,.2f}</span>"
                f"<span class='val-pend'>Falta: R$ {c1_out_pend:,.2f}</span>"
                f"</div>"
                f"</div>"

                f"<div class='ciclo-block'>"
                f"<div class='ciclo-head'><span>🗓️ 5º Dia Útil</span></div>"
                f"<div class='ciclo-row' style='margin-bottom:2px;'>"
                f"<span class='val-pago'>📥 Rec: R$ {c2_in_pago:,.2f}</span>"
                f"<span class='val-pend'>A Rec: R$ {c2_in_pend:,.2f}</span>"
                f"</div>"
                f"<div class='ciclo-row'>"
                f"<span class='val-pago'>📤 Pago: R$ {c2_out_pago:,.2f}</span>"
                f"<span class='val-pend'>Falta: R$ {c2_out_pend:,.2f}</span>"
                f"</div>"
                f"</div>"

                f"<div class='cartao-container'>"
                f"<div class='cartao-badge'>💳 Rhuan<br><b>R$ {fatura_rhuan:,.2f}</b></div>"
                f"<div class='cartao-badge'>💳 Filipe<br><b>R$ {fatura_filipe:,.2f}</b></div>"
                f"</div>"
                f"</div>"
            )

            with cols_cards[idx % 6]:
                st.markdown(html_content, unsafe_allow_html=True)
                if st.button(
                    f"🔎 Ver {m}", key=f"btn_ver_{m}", use_container_width=True
                ):
                    st.session_state.mes_ativo = m

        st.markdown("---")
        st.markdown(
            "### 📋 Checklist e Contas Detalhadas do Mês Financeiro:"
            f" **{st.session_state.mes_ativo}**"
        )
        df_mes_ativo = df_ludico[
            df_ludico["Mês_Financeiro"] == st.session_state.mes_ativo
        ].copy()

        col_c1, col_c2 = st.columns(2)

        # CHECKLIST DIA 20
        with col_c1:
            st.markdown("#### 🗓️ Ciclo Dia 20 (40% do Salário)")
            st.caption("Adiantamentos e contas fixas do dia 20")
            df_c1_list = df_mes_ativo[df_mes_ativo["Ciclo de Caixa"].str.contains("Dia 20")]

            if not df_c1_list.empty:
                for _, row in df_c1_list.iterrows():
                    pago_bool = bool(row["Pago"])
                    icone_tipo = "📥" if "Entrada" in row["Tipo"] else "📤"
                    label_item = (
                        f"{icone_tipo} **{row['Data']}** - {row['Categoria']} -"
                        f" R$ {row['Valor']:.2f} ({row['Descrição']})"
                    )

                    checked = st.checkbox(
                        label_item,
                        value=pago_bool,
                        key=f"chk_c1_{row['ID']}",
                    )
                    if checked != pago_bool:
                        alternar_status_pago(row["ID"], checked)
                        st.rerun()
            else:
                st.info("Nenhum lançamento no Ciclo Dia 20 neste mês.")

        # CHECKLIST 5º DIA ÚTIL
        with col_c2:
            st.markdown("#### 🗓️ Ciclo 5º Dia Útil (60% do Salário)")
            st.caption("Salário principal, cartões e serviços")
            df_c2_list = df_mes_ativo[df_mes_ativo["Ciclo de Caixa"].str.contains("5º Dia Útil")]

            if not df_c2_list.empty:
                for _, row in df_c2_list.iterrows():
                    pago_bool = bool(row["Pago"])
                    icone_tipo = "📥" if "Entrada" in row["Tipo"] else "📤"
                    label_item = (
                        f"{icone_tipo} **{row['Data']}** - {row['Categoria']} -"
                        f" R$ {row['Valor']:.2f} ({row['Descrição']})"
                    )

                    checked = st.checkbox(
                        label_item,
                        value=pago_bool,
                        key=f"chk_c2_{row['ID']}",
                    )
                    if checked != pago_bool:
                        alternar_status_pago(row["ID"], checked)
                        st.rerun()
            else:
                st.info("Nenhum lançamento no Ciclo 5º Dia Útil neste mês.")

# --- ABA DE INVESTIMENTOS ---
with tab_investimentos:
    st.subheader(
        "🏢 Gestão de Carteiras de Investimento (Rendimentos Atualizados Até"
        " Hoje)"
    )

    col_cadastro, col_lista = st.columns([1, 2])

    with col_cadastro:
        with st.container(border=True):
            st.markdown("#### 📥 Cadastrar Nova Alocação / Carteira")
            nome_c = st.text_input(
                "Nome do Destino/Carteira:",
                placeholder="Ex: Nubank Principal, Caixinha Reserva",
            )
            data_ap = st.date_input(
                "🗓️ Data da Aplicação / Depósito:", datetime.now()
            )
            data_ven = st.date_input(
                "🗓️ Data do Vencimento / Resgate:",
                datetime.now() + timedelta(days=90),
            )
            pct_cdi = st.number_input(
                "Rentabilidade (% do CDI):",
                min_value=10.0,
                max_value=500.0,
                value=100.0,
                step=1.0,
            )
            val_aplicado = st.number_input(
                "💵 Valor Guardado (R$):", min_value=0.0, step=50.0
            )

            btn_salvar_carteira = st.button(
                "Adicionar à Carteira 📈",
                use_container_width=True,
                type="primary",
            )
            if btn_salvar_carteira:
                if val_aplicado > 0 and nome_c != "":
                    salvar_carteira_db(
                        nome_c,
                        data_ap.strftime("%d/%m/%Y"),
                        data_ven.strftime("%d/%m/%Y"),
                        pct_cdi,
                        val_aplicado,
                    )
                    st.success(
                        f"Alocação '{nome_c}' registrada com sucesso!"
                    )
                    st.rerun()

    with col_lista:
        st.markdown(
            "#### 📦 Minhas Alocações Ativas & Rendimentos até o Momento"
        )
        df_caixas = carregar_carteiras()

        if not df_caixas.empty:
            total_patrimonio_atual = 0.0
            total_lucro_liquido_projetado = 0.0
            hoje = datetime.now()

            for _, row in df_caixas.iterrows():
                d_ap = datetime.strptime(row["data_aplicacao"], "%d/%m/%Y")
                d_ven = datetime.strptime(row["data_vencimento"], "%d/%m/%Y")

                data_limite_calculo = min(hoje, d_ven)

                dias_corridos_ate_hoje = (data_limite_calculo - d_ap).days
                if dias_corridos_ate_hoje < 0:
                    dias_corridos_ate_hoje = 0

                if dias_corridos_ate_hoje <= 180:
                    aliquota_ir = 0.225
                elif dias_corridos_ate_hoje <= 360:
                    aliquota_ir = 0.200
                elif dias_corridos_ate_hoje <= 720:
                    aliquota_ir = 0.175
                else:
                    aliquota_ir = 0.150

                aliquota_iof = calcular_aliquota_iof(dias_corridos_ate_hoje)

                taxa_cdi_diaria_pura = (
                    1 + (TAXA_CDI_ANUAL_PADRAO / 100.0)
                ) ** (1 / 252) - 1
                taxa_diaria = taxa_cdi_diaria_pura * (
                    row["porcentagem_cdi"] / 100.0
                )

                dias_uteis_reais = calcular_dias_uteis(d_ap, data_limite_calculo)

                valor_final_bruto = row["valor_aplicado"] * (
                    (1 + taxa_diaria) ** dias_uteis_reais
                )
                lucro_bruto = valor_final_bruto - row["valor_aplicado"]

                imposto_iof_retido = lucro_bruto * aliquota_iof
                lucro_base_ir = lucro_bruto - imposto_iof_retido
                imposto_ir_retido = lucro_base_ir * aliquota_ir

                lucro_liquido = (
                    lucro_bruto - imposto_iof_retido - imposto_ir_retido
                )
                valor_final_liquido = row["valor_aplicado"] + lucro_liquido

                total_patrimonio_atual += row["valor_aplicado"]
                total_lucro_liquido_projetado += lucro_liquido

                status_calc = (
                    "🟢 Rendendo" if hoje < d_ven else "🏁 Vencido/Estagnado"
                )
                texto_iof_status = (
                    f"{aliquota_iof * 100:.0f}%"
                    if aliquota_iof > 0
                    else "Isento"
                )

                st.markdown(
                    f"""
                <div class="card-invest">
                    <div style='display: flex; justify-content: space-between; align-items: center;'>
                        <span style='font-size:18px; font-weight:bold; color:#0066cc;'>📌 {row['nome_carteira']}</span>
                        <span style='font-size: 12px; font-weight: bold; padding: 3px 8px; border-radius: 20px; background-color: #e2e8f0; color: #475569;'>{status_calc}</span>
                    </div>
                    <hr style='margin:8px 0; border:0; border-top:1px solid #e2e8f0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <div>
                            <p style='margin:0; font-size:13px; color:#64748b;'>Valor Inicial</p>
                            <p style='margin:0; font-weight:bold; font-size:15px; color:#1e293b;'>R$ {row['valor_aplicado']:,.2f}</p>
                        </div>
                        <div>
                            <p style='margin:0; font-size:13px; color:#64748b;'>Taxa Contratada</p>
                            <p style='margin:0; font-weight:bold; font-size:15px; color:#0f766e;'>{row['porcentagem_cdi']}% CDI</p>
                        </div>
                        <div>
                            <p style='margin:0; font-size:13px; color:#64748b;'>Rendimento Bruto Atual</p>
                            <p style='margin:0; font-weight:bold; font-size:15px; color:#16a34a;'>+ R$ {lucro_bruto:,.2f}</p>
                        </div>
                        <div>
                            <p style='margin:0; font-size:13px; color:#f59e0b;'>IOF s/ Resgate Hoje</p>
                            <p style='margin:0; font-weight:bold; font-size:15px; color:#f59e0b;'>- R$ {imposto_iof_retido:,.2f} ({texto_iof_status})</p>
                        </div>
                        <div>
                            <p style='margin:0; font-size:13px; color:#ef4444;'>IR s/ Resgate Hoje</p>
                            <p style='margin:0; font-weight:bold; font-size:15px; color:#ef4444;'>- R$ {imposto_ir_retido:,.2f} ({aliquota_ir * 100:.1f}%)</p>
                        </div>
                        <div>
                            <p style='margin:0; font-size:13px; color:#64748b;'>Saldo Líquido Atual</p>
                            <p style='margin:0; font-weight:bold; font-size:15px; color:#003366;'>R$ {valor_final_liquido:,.2f}</p>
                        </div>
                    </div>
                    <p style='margin:8px 0 0 0; font-size:12px; color:#94a3b8;'>🗓️ Aplicado em: {row['data_aplicacao']} <br>⏱️ <b>Contagem Acumulada até Hoje:</b> {dias_corridos_ate_hoje} dias corridos decorridos / <b>{dias_uteis_reais} dias úteis capitalizados</b></p>
                </div>
                """,
                    unsafe_allow_html=True,
                )

                if st.button(
                    f"🗑️ Resgatar / Remover {row['nome_carteira']}",
                    key=f"del_cart_{row['id']}",
                    use_container_width=True,
                ):
                    deletar_carteira_db(row["id"])
                    st.rerun()

            st.markdown("---")
            st.markdown(
                "### 📊 Consolidado Acumulado em Carteira (Saldo de Hoje)"
            )
            t1, t2 = st.columns(2)
            t1.metric(
                "Capital Inicial Guardado",
                f"R$ {total_patrimonio_atual:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", "."),
            )
            t2.metric(
                "Lucro Líquido Realizado Até Hoje",
                f"R$ {total_lucro_liquido_projetado:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", "."),
                delta="Já deduzidos IOF e Imposto de Renda proporcionais",
            )
        else:
            st.caption(
                "Nenhum investimento ou caixinha específica cadastrada até o"
                " momento."
            )