"""Conecta ao PostgreSQL, executa queries analíticas e retorna os resultados como DataFrames Python."""

import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

load_dotenv()


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR/ "consultas.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


PASTA = Path("data/processed")
PASTA.mkdir(parents=True, exist_ok=True)


def conectar():
    """
    Cria a engine SQLAlchemy a partir de variáveis de ambiente
    e valida a conexão com o banco antes de retornar.

    Por que validar com SELECT 1?
      - create_engine() é lazy: só tenta conectar de verdade quando
        você executa a primeira query. Testamos aqui para falhar
        cedo, com mensagem clara, em vez de explodir no meio da execução.
    """
    host     = os.getenv("DB_HOST",     "localhost")
    port     = os.getenv("DB_PORT",     "5432")
    database = os.getenv("DB_NAME",     "saas_analytics")
    user     = os.getenv("DB_USER",     "postgres")
    password = os.getenv("DB_PASSWORD", "")

    url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("Conectado ao PostgreSQL em %s:%s/%s", host, port, database)
        return engine
    except OperationalError as exc:
        log.error("Falha ao conectar ao banco: %s", exc)
        raise




def rodar(engine, sql: str, titulo: str) -> pd.DataFrame:
    """ Executa uma query SQL e retorna um DataFrame. """
    separador = "─" * 55
    log.info(separador)
    log.info("  %s", titulo)
    log.info(separador)

    try:
        df = pd.read_sql(text(sql), engine)
    except SQLAlchemyError as exc:
        log.error("Erro ao executar '%s': %s", titulo, exc)
        raise

    log.info("\n%s", df.to_string(index=False))
    log.info("  → %d linha(s) retornada(s)\n", len(df))
    return df




SQL_MRR = """
    -- MRR mensal com crescimento mês a mês
    --
    -- LAG(mrr) OVER (ORDER BY year_month) busca o valor do mês anterior
    -- dentro da janela ordenada por período. Sem window function,
    -- precisaríamos de um self-join muito mais verboso.
    --
    -- NULLIF(x, 0) evita divisão por zero: retorna NULL se x = 0,
    -- e NULL / qualquer_coisa = NULL (não levanta exceção).
    SELECT
        year_month                                                   AS periodo,
        ROUND(mrr::NUMERIC, 2)                                       AS mrr,
        ROUND(arr::NUMERIC, 2)                                       AS arr,
        clientes_ativos,
        ROUND(arpu::NUMERIC, 2)                                      AS arpu,
        ROUND(margem_pct::NUMERIC, 2)                                AS margem_pct,
        ROUND(
            (mrr - LAG(mrr) OVER (ORDER BY year_month))
            / NULLIF(LAG(mrr) OVER (ORDER BY year_month), 0)
            * 100,
        2)                                                           AS crescimento_mom_pct
    FROM vw_receita_mensal
    ORDER BY year_month
"""

SQL_SEGMENTOS = """
    -- Receita, margem e share por segmento de cliente
    --
    -- SUM(SUM(sales)) OVER () é uma window function aninhada:
    --   - o SUM interno é do GROUP BY (total por segmento)
    --   - o SUM externo soma TODOS os totais (total geral)
    -- Isso permite calcular o percentual de cada segmento sem
    -- precisar de uma subquery separada.
    SELECT
        segment                                                      AS segmento,
        COUNT(DISTINCT customer_id)                                  AS clientes,
        ROUND(SUM(sales)::NUMERIC, 2)                                AS receita_total,
        ROUND(SUM(profit)::NUMERIC, 2)                               AS lucro_total,
        ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)         AS margem_pct,
        ROUND(SUM(sales) / SUM(SUM(sales)) OVER () * 100, 2)        AS share_pct,
        ROUND(SUM(sales) / NULLIF(COUNT(DISTINCT customer_id), 0), 2) AS arpu
    FROM vendas
    GROUP BY segment
    ORDER BY receita_total DESC
"""

SQL_TOP_PRODUTOS = """
    -- Top 10 produtos por receita, com ranking via RANK()
    --
    -- RANK() numera as linhas do maior para o menor valor de receita.
    -- Diferente de ROW_NUMBER(), RANK() repete o número em caso de empate:
    -- se dois produtos têm a mesma receita, ambos ficam com rank 1
    -- e o próximo fica com rank 3 (não 2).
    SELECT
        RANK() OVER (ORDER BY SUM(sales) DESC)                       AS rank,
        product                                                      AS produto,
        COUNT(DISTINCT customer_id)                                  AS clientes,
        ROUND(SUM(sales)::NUMERIC, 2)                                AS receita_total,
        ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)         AS margem_pct,
        ROUND(AVG(discount) * 100, 2)                                AS desconto_medio_pct
    FROM vendas
    GROUP BY product
    ORDER BY receita_total DESC
    LIMIT 10
"""

SQL_TOP_CLIENTES = """
    -- Top 10 clientes por receita com share do total
    SELECT
        customer_name                                                AS cliente,
        segment                                                      AS segmento,
        ROUND(SUM(sales)::NUMERIC, 2)                                AS receita_total,
        ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)         AS margem_pct,
        ROUND(SUM(sales) / SUM(SUM(sales)) OVER () * 100, 2)        AS share_pct
    FROM vendas
    GROUP BY customer_name, segment
    ORDER BY receita_total DESC
    LIMIT 10
"""

SQL_TRIMESTRAL = """
    -- Receita por ano e trimestre (visão para DRE)
    SELECT
        year                                                         AS ano,
        quarter                                                      AS trimestre,
        ROUND(SUM(sales)::NUMERIC, 2)                                AS receita,
        ROUND(SUM(profit)::NUMERIC, 2)                               AS lucro,
        ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)         AS margem_pct,
        COUNT(DISTINCT customer_id)                                  AS clientes
    FROM vendas
    GROUP BY year, quarter
    ORDER BY year, quarter
"""

SQL_DESCONTOS = """
    -- Impacto do desconto na margem bruta
    --
    -- CASE WHEN transforma o valor contínuo de desconto (0.0 a 1.0)
    -- em faixas categóricas. Facilita identificar o ponto de inflexão
    -- onde o desconto passa a destruir a margem.
    SELECT
        CASE
            WHEN discount = 0     THEN '0%  — sem desconto'
            WHEN discount <= 0.10 THEN '1% a 10%'
            WHEN discount <= 0.20 THEN '11% a 20%'
            WHEN discount <= 0.30 THEN '21% a 30%'
            ELSE                       'Acima de 30%'
        END                                                          AS faixa_desconto,
        COUNT(*)                                                     AS pedidos,
        ROUND(SUM(sales)::NUMERIC, 2)                                AS receita_total,
        ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 2)         AS margem_pct
    FROM vendas
    GROUP BY faixa_desconto
    ORDER BY MIN(discount)
"""


QUERIES = {
    "1. MRR Mensal com Crescimento MoM":     (SQL_MRR,          "sql_mrr_mensal.csv"),
    "2. Receita por Segmento":               (SQL_SEGMENTOS,    "sql_segmentos.csv"),
    "3. Top 10 Produtos por Receita":        (SQL_TOP_PRODUTOS, "sql_top_produtos.csv"),
    "4. Top 10 Clientes por Receita":        (SQL_TOP_CLIENTES, "sql_top_clientes.csv"),
    "5. Receita por Trimestre":              (SQL_TRIMESTRAL,   "sql_trimestral.csv"),
    "6. Impacto do Desconto na Margem":      (SQL_DESCONTOS,    "sql_descontos.csv"),
}



def main() -> None:
    log.info("=" * 55)
    log.info("   Consultas SQL — SaaS Sales Analytics")
    log.info("=" * 55)

    try:
        engine = conectar()
    except Exception:
        log.critical("Não foi possível conectar ao banco. Abortando.")
        sys.exit(1)

    erros = []


    for titulo, (sql, arquivo) in QUERIES.items():
        try:
            df = rodar(engine, sql, titulo)
            df.to_csv(PASTA / arquivo, index=False)
            log.info("  Salvo em data/processed/%s", arquivo)
        except Exception as exc:
            log.error("Falha em '%s': %s", titulo, exc)
            erros.append(titulo)

    engine.dispose()

    if erros:
        log.warning("Queries com falha: %s", erros)
    else:
        log.info("Todos os resultados salvos em data/processed/")
        log.info("Consultas concluídas")


if __name__ == "__main__":
    main()