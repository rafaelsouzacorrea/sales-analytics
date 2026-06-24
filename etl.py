"""
Lê o arquivo CSV bruto do Kaggle, limpa os dados
e salva no PostgreSQL para análise.
"""

import os
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv


load_dotenv()

ARQUIVO_BRUTO = 'data/raw/saas_bruto.csv'
ARQUIVO_LIMPO = 'data/processed/saas_limpo.csv'


DB_URL = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)


RENOMEAR = {
    'Row ID':       'row_id',
    'Order ID':     'order_id',
    'Order Date':   'order_date',
    'Date Key':     'date_key',
    'Contact Name': 'contact_name',
    'Country':      'country',
    'City':         'city',
    'Region':       'region',
    'Subregion':    'subregion',
    'Customer':     'customer_name',
    'Customer ID':  'customer_id',
    'Industry':     'industry',
    'Segment':      'segment',
    'Product':      'product',
    'License':      'license',
    'Sales':        'sales',
    'Quantity':     'quantity',
    'Discount':     'discount',
    'Profit':       'profit',
}


def carregar(caminho):
    """Lê o CSV bruto do Kaggle."""
    print(f"\n[1/3] Carregando: {caminho}")
    df = pd.read_csv(caminho)
    print(f"      {len(df):,} linhas encontradas")
    return df


def limpar(df):
    """ Limpa e prepara os dados para análise. """
    
    print("\n[2/3] Limpando os dados...")

    
    df = df.rename(columns=RENOMEAR)

    df['order_date'] = pd.to_datetime(df['order_date'])

    df['sales']    = pd.to_numeric(df['sales'],    errors='coerce')
    df['profit']   = pd.to_numeric(df['profit'],   errors='coerce')
    df['discount'] = pd.to_numeric(df['discount'], errors='coerce').fillna(0)

    antes = len(df)
    df = df.drop_duplicates(subset=['row_id'])          
    df = df.dropna(subset=['sales', 'customer_id', 'order_date']) 
    print(f"      {antes - len(df)} linhas removidas | {len(df):,} restantes")


    df['year']       = df['order_date'].dt.year
    df['month']      = df['order_date'].dt.month
    df['quarter']    = df['order_date'].dt.quarter
    df['year_month'] = df['order_date'].dt.to_period('M').astype(str)  # ex: "2023-01"

    for col in ['customer_name', 'segment', 'product', 'region']:
        df[col] = df[col].astype(str).str.strip()

    print("Limpeza concluída")
    return df



def salvar(df, caminho_csv, db_url):
    """
    Salva os dados em dois destinos:
      - CSV:        para usar no Excel e Power BI
      - PostgreSQL: para fazer queries SQL analíticas
    """
    print("\n[3/3] Salvando dados...")

   
    os.makedirs('data/processed', exist_ok=True)
    df.to_csv(caminho_csv, index=False)
    print(f"      CSV salvo em: {caminho_csv}")

    print(f"      DB_URL: {repr(db_url)}")   # ← adicione essa linha
    engine = create_engine(db_url)
    df.to_sql('vendas', engine, if_exists='replace', index=False, chunksize=1000)
    print("      Tabela 'vendas' carregada no PostgreSQL")



def main():
    print("=" * 45)
    print("   ETL — SaaS Sales Analytics")
    print("=" * 45)

    df_bruto = carregar(ARQUIVO_BRUTO)
    df_limpo = limpar(df_bruto)
    salvar(df_limpo, ARQUIVO_LIMPO, DB_URL)

    print("\nResumo dos dados carregados:")
    print(f"   Período      : {df_limpo['order_date'].min().date()} → {df_limpo['order_date'].max().date()}")
    print(f"   Transações   : {len(df_limpo):,}")
    print(f"   Clientes     : {df_limpo['customer_id'].nunique():,}")
    print(f"   Produtos     : {df_limpo['product'].nunique():,}")
    print(f"   Receita total: ${df_limpo['sales'].sum():,.2f}")
    print("\nETL concluído")


if __name__ == '__main__':
    main()