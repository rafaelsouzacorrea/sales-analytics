"""
Consultas SQL — SaaS Sales Analytics
======================================
Conecta ao PostgreSQL, executa queries analíticas
e retorna os resultados como DataFrames Python.

Por que usar SQL aqui e não só pandas?
  - SQL roda dentro do banco: mais eficiente para tabelas grandes
  - Window functions (LAG, RANK) são mais legíveis em SQL
  - As mesmas queries rodam no Power BI, Metabase, DBeaver etc.
  - Demonstra que você sabe usar SQL em contexto real

Como rodar:
    python consultas.py   (rode o etl.py antes!)
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# ── Conexão com o banco ───────────────────────────────────────
DB_URL = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

PASTA = Path('data/processed')
PASTA.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# CONEXÃO
# ══════════════════════════════════════════════════════════════

def conectar():
    """Cria a conexão com o PostgreSQL e valida que está funcionando."""
    engine = create_engine(DB_URL)

    # Testa a conexão com uma query simples antes de continuar
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    print("✓ Conectado ao PostgreSQL\n")
    return engine


# ══════════════════════════════════════════════════════════════
# EXECUTOR DE QUERIES
# ══════════════════════════════════════════════════════════════

def rodar(engine, sql, titulo):
    """
    Executa uma query SQL no PostgreSQL e retorna um DataFrame.

    pd.read_sql() faz três coisas automaticamente:
      1. Envia a query para o PostgreSQL
      2. Recebe o resultado
      3. Converte para DataFrame — pronto para usar em Python
    """
    print(f"{'─' * 55}")
    print(f"  {titulo}")
    print(f"{'─' * 55}")

    df = pd.read_sql(text(sql), engine)

    print(df.to_string(index=False))
    print(f"\n  → {len(df)} linha(s) retornada(s)\n")
    return df


# ══════════════════════════════════════════════════════════════
# QUERIES ANALÍTICAS
# ══════════════════════════════════════════════════════════════

SQL_MRR = """
    -- MRR mensal com crescimento mês a mês
    -- LAG() busca o valor da linha anterior dentro da janela ordenada
    -- Sem window function, precisaríamos de um self-join muito mais complexo
    SELECT
        year_month                                               AS periodo,
        ROUND(mrr::NUMERIC, 2)                                   AS mrr,
        ROUND(arr::NUMERIC, 2)                                   AS arr,
        clientes_ativos,
        ROUND(arpu::NUMERIC, 2)                                  AS arpu,
        ROUND(margem_pct::NUMERIC, 2)                            AS margem_pct,
        ROUND(
            (mrr - LAG(mrr) OVER (ORDER BY year_month))
            / NULLIF(LAG(mrr) OVER (ORDER BY year_month), 0)
            * 100,
        2)                                                       AS crescimento_mom_pct
    FROM vw_receita_mensal
    ORDER BY year_month
"""

SQL_SEGMENTOS = """
    -- Receita, margem e share por segmento de cliente
    -- SUM(SUM(sales)) OVER () = total geral, sem GROUP BY
    -- Isso permite calcular o percentual de cada segmento no total
    SELECT
        segment                                                  AS segmento,
        COUNT(DISTINCT customer_id)                              AS clientes,
        ROUND(SUM(sales)::NUMERIC, 2)                            AS receita_total,
        ROUND(SUM(profit)::NUMERIC, 2)                           AS lucro_total,
        ROUND(
            SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)       AS margem_pct,
        ROUND(
            SUM(sales) / SUM(SUM(sales)) OVER () * 100, 2)      AS share_pct,
        ROUND(
            SUM(sales) / NULLIF(COUNT(DISTINCT customer_id), 0),
        2)                                                       AS arpu
    FROM vendas
    GROUP BY segment
    ORDER BY receita_total DESC
"""

SQL_TOP_PRODUTOS = """
    -- Top 10 produtos por receita, com ranking automático via RANK()
    -- RANK() numera os grupos do maior para o menor dentro da janela
    SELECT
        RANK() OVER (ORDER BY SUM(sales) DESC)                   AS rank,
        product                                                  AS produto,
        COUNT(DISTINCT customer_id)                              AS clientes,
        ROUND(SUM(sales)::NUMERIC, 2)                            AS receita_total,
        ROUND(
            SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)       AS margem_pct,
        ROUND(AVG(discount) * 100, 2)                            AS desconto_medio_pct
    FROM vendas
    GROUP BY product
    ORDER BY receita_total DESC
    LIMIT 10
"""

SQL_TOP_CLIENTES = """
    -- Top 10 clientes por receita com share do total
    SELECT
        customer_name                                            AS cliente,
        segment                                                  AS segmento,
        ROUND(SUM(sales)::NUMERIC, 2)                            AS receita_total,
        ROUND(
            SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)       AS margem_pct,
        ROUND(
            SUM(sales) / SUM(SUM(sales)) OVER () * 100, 2)      AS share_pct
    FROM vendas
    GROUP BY customer_name, segment
    ORDER BY receita_total DESC
    LIMIT 10
"""

SQL_TRIMESTRAL = """
    -- Receita por ano e trimestre (visão para DRE)
    SELECT
        year                                                     AS ano,
        quarter                                                  AS trimestre,
        ROUND(SUM(sales)::NUMERIC, 2)                            AS receita,
        ROUND(SUM(profit)::NUMERIC, 2)                           AS lucro,
        ROUND(
            SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)       AS margem_pct,
        COUNT(DISTINCT customer_id)                              AS clientes
    FROM vendas
    GROUP BY year, quarter
    ORDER BY year, quarter
"""

SQL_DESCONTOS = """
    -- Impacto do desconto na margem bruta
    -- CASE WHEN cria faixas a partir de um valor contínuo
    -- Mostra como descontos maiores destroem a margem
    SELECT
        CASE
            WHEN discount = 0     THEN '0%  — sem desconto'
            WHEN discount <= 0.10 THEN '1% a 10%'
            WHEN discount <= 0.20 THEN '11% a 20%'
            WHEN discount <= 0.30 THEN '21% a 30%'
            ELSE                       'Acima de 30%'
        END                                                      AS faixa_desconto,
        COUNT(*)                                                 AS pedidos,
        ROUND(SUM(sales)::NUMERIC, 2)                            AS receita_total,
        ROUND(
            SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)       AS margem_pct
    FROM vendas
    GROUP BY faixa_desconto
    ORDER BY MIN(discount)
"""


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 55)
    print("   Consultas SQL — SaaS Sales Analytics")
    print("=" * 55 + "\n")

    engine = conectar()

    # Executar cada query e guardar o resultado
    mrr        = rodar(engine, SQL_MRR,          "1. MRR Mensal com Crescimento MoM")
    segmentos  = rodar(engine, SQL_SEGMENTOS,    "2. Receita por Segmento")
    produtos   = rodar(engine, SQL_TOP_PRODUTOS, "3. Top 10 Produtos por Receita")
    clientes   = rodar(engine, SQL_TOP_CLIENTES, "4. Top 10 Clientes por Receita")
    trimestral = rodar(engine, SQL_TRIMESTRAL,   "5. Receita por Trimestre")
    descontos  = rodar(engine, SQL_DESCONTOS,    "6. Impacto do Desconto na Margem")

    # Salvar resultados — podem ser abertos no Excel ou Power BI
    mrr.to_csv(PASTA        / 'sql_mrr_mensal.csv',   index=False)
    segmentos.to_csv(PASTA  / 'sql_segmentos.csv',    index=False)
    produtos.to_csv(PASTA   / 'sql_top_produtos.csv', index=False)
    clientes.to_csv(PASTA   / 'sql_top_clientes.csv', index=False)
    trimestral.to_csv(PASTA / 'sql_trimestral.csv',   index=False)
    descontos.to_csv(PASTA  / 'sql_descontos.csv',    index=False)

    print("✓ Todos os resultados salvos em data/processed/")
    print("✅ Consultas concluídas!")


if __name__ == '__main__':
    main()