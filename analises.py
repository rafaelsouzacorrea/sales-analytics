"""
Análises — SaaS Sales Analytics

KPIs calculados:
  MRR   Monthly Recurring Revenue  → receita total do mês
  ARR   Annual Recurring Revenue   → MRR × 12
  ARPU  Avg Revenue Per User       → MRR ÷ clientes ativos
  Churn Taxa de saída de clientes  → % que não voltaram no mês seguinte
  LTV   Customer Lifetime Value    → ARPU ÷ Churn Rate

"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

ARQUIVO       = 'data/processed/saas_limpo.csv'
PASTA_CSV     = Path('data/processed')
PASTA_GRAFICOS = Path('docs/plots')
PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)


def carregar():
    """Lê o CSV gerado pelo ETL e recria a coluna de período."""
    df = pd.read_csv(ARQUIVO, parse_dates=['order_date'])
    # Period('M') agrupa datas pelo mês — ex: 2023-01-05 vira "2023-01"
    df['year_month'] = df['order_date'].dt.to_period('M')
    return df



# KPI 1 - MRR MENSAL
def calcular_mrr(df):
    """
    Agrupa vendas por mês e calcula os principais KPIs de receita.

    MRR  = soma das vendas no mês
    ARR  = MRR × 12  (quanto isso representa ao ano)
    ARPU = MRR ÷ clientes ativos  (ticket médio por cliente)
    Crescimento MoM = quanto o MRR cresceu em relação ao mês anterior
    """
    mrr = df.groupby('year_month').agg(
        mrr             = ('sales',       'sum'),       
        clientes_ativos = ('customer_id', 'nunique'),   
        pedidos         = ('order_id',    'nunique'),   
        lucro           = ('profit',      'sum'),        
    ).reset_index()

    
    mrr['arr']          = mrr['mrr'] * 12
    mrr['arpu']         = (mrr['mrr'] / mrr['clientes_ativos']).round(2)
    mrr['margem_pct']   = (mrr['lucro'] / mrr['mrr'] * 100).round(2)

    
    mrr['crescimento_mom_pct'] = mrr['mrr'].pct_change().mul(100).round(2)

    
    mrr['year_month'] = mrr['year_month'].astype(str)
    return mrr



# KPI 2 - CHURN RATE
def calcular_churn(df):
    """Churn Rate = % de clientes que compraram no mês T mas não compraram em T+1."""
    
    atividade = (
        df.groupby(['year_month', 'customer_id'])
        .size()
        .reset_index(name='pedidos')
    )

   
    pivot = atividade.pivot_table(
        index='customer_id',
        columns='year_month',
        values='pedidos',
        fill_value=0,   
    )

    meses = sorted(pivot.columns)
    resultados = []

    
    for i in range(1, len(meses)):
        mes_anterior = meses[i - 1]
        mes_atual    = meses[i]

    
        ativos_antes = set(pivot.index[pivot[mes_anterior] > 0])
        ativos_agora = set(pivot.index[pivot[mes_atual]    > 0])

      
        sairam   = ativos_antes - ativos_agora   # estavam, não voltaram
        chegaram = ativos_agora - ativos_antes   # não estavam, apareceram

        churn = len(sairam) / len(ativos_antes) if ativos_antes else 0

        resultados.append({
            'periodo':      str(mes_atual),
            'clientes_ini': len(ativos_antes),
            'clientes_fim': len(ativos_agora),
            'novos':        len(chegaram),
            'sairam':       len(sairam),
            'churn_pct':    round(churn * 100, 2),
            'retencao_pct': round((1 - churn) * 100, 2),
        })

    return pd.DataFrame(resultados)


# KPI 3 - LTV
def calcular_ltv(mrr_df, churn_df):
    """
    LTV = ARPU ÷ Churn Rate mensal

    Raciocínio simples:
      Se um cliente gera $100/mês (ARPU) e 10% dos clientes
      saem por mês (churn), a vida média é 1/0.10 = 10 meses.
      LTV = $100 × 10 meses = $1.000
    """
    arpu_medio    = mrr_df['arpu'].mean()
    churn_decimal = churn_df['churn_pct'].mean() / 100  

    if churn_decimal > 0:
        meses_vida = 1 / churn_decimal
        ltv        = arpu_medio * meses_vida
    else:
        meses_vida = None
        ltv        = None

    return {
        'arpu_medio': round(arpu_medio, 2),
        'churn_pct':  round(churn_decimal * 100, 2),
        'meses_vida': round(meses_vida, 1) if meses_vida else None,
        'ltv':        round(ltv, 2) if ltv else None,
    }


# Análise por segmento
def por_segmento(df):
    """
    Agrupa receita, lucro e clientes por segmento.
    Segmentos: SMB, Strategic, Enterprise, Government.
    """
    seg = df.groupby('segment').agg(
        receita = ('sales',       'sum'),
        lucro   = ('profit',      'sum'),
        clientes= ('customer_id', 'nunique'),
        pedidos = ('order_id',    'nunique'),
    ).reset_index()

    seg['margem_pct'] = (seg['lucro']   / seg['receita'] * 100).round(2)
    seg['share_pct']  = (seg['receita'] / seg['receita'].sum() * 100).round(2)
    seg['arpu']       = (seg['receita'] / seg['clientes']).round(2)

    return seg.sort_values('receita', ascending=False)


# Análise por Produto
def por_produto(df):
    """Agrupa receita e margem por produto."""
    prod = df.groupby('product').agg(
        receita = ('sales',  'sum'),
        lucro   = ('profit', 'sum'),
        clientes= ('customer_id', 'nunique'),
    ).reset_index()

    prod['margem_pct'] = (prod['lucro']   / prod['receita'] * 100).round(2)
    prod['share_pct']  = (prod['receita'] / prod['receita'].sum() * 100).round(2)

    return prod.sort_values('receita', ascending=False)


# Gráficos
def grafico_mrr(mrr_df):
    """Gráfico de linha: evolução do MRR mês a mês."""
    fig, ax = plt.subplots(figsize=(13, 5))

    x = list(range(len(mrr_df)))       
    y = mrr_df['mrr'].values           

    ax.plot(x, y, marker='o', linewidth=2.5, color='#2563EB', markersize=5)
    ax.fill_between(x, y, alpha=0.08, color='#2563EB')  

    ax.set_title('MRR Mensal — Evolução da Receita', fontsize=14, fontweight='bold')
    ax.set_ylabel('Receita (USD)')
    ax.set_xticks(x)
    ax.set_xticklabels(mrr_df['year_month'].tolist(), rotation=45, ha='right', fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'${v:,.0f}'))
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    plt.savefig(PASTA_GRAFICOS / 'mrr_mensal.png', dpi=150)
    print("  ✓ docs/plots/mrr_mensal.png")
    plt.show()


def grafico_segmentos(seg_df):
    """Dois gráficos lado a lado: receita e margem por segmento."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle('Análise por Segmento de Cliente', fontsize=14, fontweight='bold')

    cores = ["#092C79", '#7C3AED', '#059669', '#DC2626']

    ax1.bar(seg_df['segment'], seg_df['receita'], color=cores)
    ax1.set_title('Receita Total por Segmento')
    ax1.set_ylabel('Receita (USD)')
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'${v:,.0f}'))
    ax1.tick_params(axis='x', rotation=15)

    ax2.bar(seg_df['segment'], seg_df['margem_pct'], color=cores)
    ax2.set_title('Margem Bruta por Segmento (%)')
    ax2.set_ylabel('Margem (%)')
    ax2.tick_params(axis='x', rotation=15)

    plt.tight_layout()
    plt.savefig(PASTA_GRAFICOS / 'segmentos.png', dpi=150)
    print("  ✓ docs/plots/segmentos.png")
    plt.show()



def main():
    print("=" * 45)
    print("   Análises — SaaS Sales Analytics")
    print("=" * 45)

    df = carregar()

    # Calcular KPIs
    mrr_df   = calcular_mrr(df)
    churn_df = calcular_churn(df)
    ltv      = calcular_ltv(mrr_df, churn_df)
    seg_df   = por_segmento(df)
    prod_df  = por_produto(df)

    ultimo = mrr_df.iloc[-1]

    print(f"\nKPIs - último mês ({ultimo['year_month']}):")
    print(f"   MRR             : ${float(ultimo['mrr']):>10,.2f}")
    print(f"   ARR             : ${float(ultimo['arr']):>10,.2f}")
    print(f"   ARPU            : ${float(ultimo['arpu']):>10,.2f}")
    print(f"   Clientes ativos : {int(ultimo['clientes_ativos']):>10,}")
    print(f"   Margem bruta    : {float(ultimo['margem_pct']):>9.2f}%")

    print(f"\nMédias históricas:")
    print(f"   Churn Rate mensal  : {churn_df['churn_pct'].mean():>7.2f}%")
    print(f"   Retenção mensal    : {churn_df['retencao_pct'].mean():>7.2f}%")
    if ltv['ltv']:
        print(f"   LTV estimado       : ${ltv['ltv']:>9,.2f}")
        print(f"   Vida média (meses) : {ltv['meses_vida']:>7.1f}")

    print(f"\nReceita por segmento:")
    print(seg_df[['segment', 'receita', 'margem_pct', 'share_pct', 'arpu']].to_string(index=False))

    # ── Salvar CSVs ──────────────────────────────────────────
    mrr_df.to_csv(PASTA_CSV  / 'mrr_mensal.csv',    index=False)
    churn_df.to_csv(PASTA_CSV / 'churn_mensal.csv', index=False)
    seg_df.to_csv(PASTA_CSV  / 'por_segmento.csv',  index=False)
    prod_df.to_csv(PASTA_CSV / 'por_produto.csv',   index=False)
    print(f"\nCSVs salvos em data/processed/")

    # ── Gráficos ─────────────────────────────────────────────
    print("\nGerando gráficos...")
    grafico_mrr(mrr_df)
    grafico_segmentos(seg_df)

    print("\nAnálise concluída")


if __name__ == '__main__':
    main()