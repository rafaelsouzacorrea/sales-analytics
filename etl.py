"""
ETL — SaaS Sales Analytics
Lê o arquivo CSV bruto do Kaggle, limpa os dados
e salva no PostgreSQL para análise posterior.

Fluxo:
    1. carregar()  | lê o CSV bruto
    2. limpar()    | normaliza tipos, remove duplicatas e nulos
    3. salvar()    | grava CSV limpo + tabela PostgreSQL + view analítica


Pré-requisitos:
    pip install -r requirements.txt
    Arquivo .env com as variáveis de banco
"""

import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from urllib.parse import quote_plus


load_dotenv()

ARQUIVO_BRUTO = Path("data/raw/saas_bruto.csv")
ARQUIVO_LIMPO = Path("data/processed/saas_limpo.csv")

#Logging
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# O console do Windows usa cp1252 por padrao e nao suporta certos
# caracteres que podiam aparecer nos logs, o que quebrava o StreamHandler.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR/ "etl.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


RENOMEAR = {
    "Row ID":       "row_id",
    "Order ID":     "order_id",
    "Order Date":   "order_date",
    "Date Key":     "date_key",
    "Contact Name": "contact_name",
    "Country":      "country",
    "City":         "city",
    "Region":       "region",
    "Subregion":    "subregion",
    "Customer":     "customer_name",
    "Customer ID":  "customer_id",
    "Industry":     "industry",
    "Segment":      "segment",
    "Product":      "product",
    "License":      "license",
    "Sales":        "sales",
    "Quantity":     "quantity",
    "Discount":     "discount",
    "Profit":       "profit",
}


def criar_engine():
    """ Cria a engine SQLAlchemy a partir de variáveis de ambiente. """

    host     = os.getenv("DB_HOST",     "localhost")
    port     = os.getenv("DB_PORT",     "5432")
    database = os.getenv("DB_NAME",     "saas_analytics")
    user     = os.getenv("DB_USER",     "postgres")
    password = os.getenv("DB_PASSWORD", "")
  
    url = (
        f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:{port}/{database}"
    )

    try:
        engine = create_engine(url, pool_pre_ping=True)

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("Conectado ao PostgreSQL em %s:%s/%s", host, port, database)
        return engine
    
    except OperationalError as exc:
        log.error("Falha ao conectar ao PostgreSQL: %s", exc)
        raise


def carregar(caminho: Path) -> pd.DataFrame:
    """Lê o CSV bruto e retorna um DataFrame."""
    
    log.info("[1/3] Carregando: %s", caminho)

    if not caminho.exists():
        log.error(
            "Arquivo não encontrado: %s\n",
            caminho.resolve(),
        )
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    ENCODINGS = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]

    df = None
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(caminho, low_memory=False, encoding=enc)
            log.info("  CSV lido com encoding '%s'", enc)
            break
        except UnicodeDecodeError:
            log.debug("  Encoding '%s' falhou, tentando próximo...", enc)

    if df is None:
        raise ValueError(f"Não foi possível ler '{caminho}' com nenhum encoding conhecido: {ENCODINGS}")

    log.info("  %d linhas e %d colunas encontradas", *df.shape)
    return df


def limpar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza tipos, remove duplicatas e linhas inválidas,
    e deriva colunas de data para facilitar análises futuras.
    """
    log.info("[2/3] Limpando os dados...")

    linhas_originais = len(df)

    colunas_faltando = set(RENOMEAR) - set(df.columns)
    if colunas_faltando:
        log.error("Colunas ausentes no CSV: %s", colunas_faltando)
        raise ValueError(f"Colunas ausentes: {colunas_faltando}")

    df = df.rename(columns=RENOMEAR)

    df["sales"]    = pd.to_numeric(df["sales"],    errors="coerce")
    df["profit"]   = pd.to_numeric(df["profit"],   errors="coerce")
    df["discount"] = pd.to_numeric(df["discount"], errors="coerce").fillna(0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")

   
    datas_invalidas = df["order_date"].isna().sum()
    if datas_invalidas > 0:
        log.warning(
            "  %d linhas com order_date inválida serão removidas",
            datas_invalidas,
        )

    df = df.drop_duplicates(subset=["row_id"])
    df = df.dropna(subset=["sales", "customer_id", "order_date", "quantity", "profit"])

    removidas = linhas_originais - len(df)
    log.info(
        "  %d linhas removidas (dup. + nulos) | %d restantes",
        removidas, len(df),
    )


    df["year"]       = df["order_date"].dt.year
    df["month"]      = df["order_date"].dt.month
    df["quarter"]    = df["order_date"].dt.quarter
    df["year_month"] = df["order_date"].dt.to_period("M").astype(str)


    for col in ["customer_name", "segment", "product", "region"]:
        df[col] = df[col].astype(str).str.strip()

    log.info("  Limpeza concluída")
    return df


def salvar(df: pd.DataFrame, caminho_csv: Path) -> None:
    """
    Salva os dados limpos em dois destinos:
      1. CSV, para abrir no Excel ou Power BI sem banco de dados
      2. PostgreSQL, tabela 'vendas' + view vw_receita_mensal
    """
    log.info("[3/3] Salvando dados...")

    #csv
    caminho_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho_csv, index=False)
    log.info("  CSV salvo em: %s", caminho_csv)

    #postgreesql
    engine = criar_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE vendas RESTART IDENTITY"))
            log.info("  Tabela 'vendas' truncada")
            df.to_sql(
                "vendas",
                conn,
                if_exists="append",
                index=False,
                chunksize=1000,
            )
        log.info("  Tabela 'vendas' carregada no PostgreSQL (%d linhas)", len(df))

      
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE OR REPLACE VIEW vw_receita_mensal AS
                SELECT
                    year_month,
                    year,
                    month,
                    SUM(sales)                                           AS mrr,
                    SUM(sales) * 12                                      AS arr,
                    COUNT(DISTINCT customer_id)                          AS clientes_ativos,
                    ROUND(
                        SUM(sales) / NULLIF(COUNT(DISTINCT customer_id), 0),
                        2
                    )                                                    AS arpu,
                    SUM(profit)                                          AS lucro_bruto,
                    ROUND(
                        SUM(profit) / NULLIF(SUM(sales), 0) * 100,
                        2
                    )                                                    AS margem_pct,
                    COUNT(DISTINCT order_id)                             AS pedidos
                FROM vendas
                GROUP BY year_month, year, month
            """))
        log.info("  View vw_receita_mensal criada/atualizada")

    except SQLAlchemyError as exc:
        log.error("Erro ao salvar no PostgreSQL: %s", exc)
        raise
    finally:
        engine.dispose()


def main() -> None:
    log.info("ETL — SaaS Sales Analytics")

    try:
        df_bruto = carregar(ARQUIVO_BRUTO)
        df_limpo = limpar(df_bruto)
        salvar(df_limpo, ARQUIVO_LIMPO)
    except Exception as exc:

        log.critical("ETL encerrado com erro: %s", exc)
        sys.exit(1)

    log.info("")
    log.info("Resumo dos dados carregados:")
    log.info("  Período      : %s -> %s",
             df_limpo["order_date"].min().date(),
             df_limpo["order_date"].max().date())
    log.info("  Transações   : %d", len(df_limpo))
    log.info("  Clientes     : %d", df_limpo["customer_id"].nunique())
    log.info("  Produtos     : %d", df_limpo["product"].nunique())
    log.info("  Receita total: $%.2f", df_limpo["sales"].sum())
    log.info("ETL concluído com sucesso")


if __name__ == "__main__":
    main()