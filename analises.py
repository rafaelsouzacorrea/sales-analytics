"""
Análises — SaaS Sales Analytics
==================================
Calcula KPIs de SaaS a partir do CSV gerado pelo ETL
e produz gráficos para o portfólio.

KPIs calculados:
  MRR   Monthly Recurring Revenue  → receita total do mês
  ARR   Annual Recurring Revenue   → MRR × 12
  ARPU  Avg Revenue Per User       → MRR ÷ clientes ativos
  Churn Taxa de saída de clientes  → % que não voltaram no mês seguinte
  LTV   Customer Lifetime Value    → ARPU ÷ Churn Rate
"""

import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd


ARQUIVO        = Path("data/processed/saas_limpo.csv")
PASTA_CSV      = Path("data/processed")
PASTA_GRAFICOS = Path("docs/plots")

PASTA_CSV.mkdir(parents=True, exist_ok=True)
PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR/ "analises.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)



def carregar() -> pd.DataFrame:
    """Lê o CSV gerado pelo ETL e recria a coluna de período."""
    if not ARQUIVO.exists():
        log.error(
            "Arquivo não encontrado: %s\n"
            "Execute o etl.py primeiro para gerar o CSV limpo.",
            ARQUIVO.resolve(),
        )
        raise FileNotFoundError(f"Arquivo ausente: {ARQUIVO}")

    log.info("Carregando %s...", ARQUIVO)


    df = pd.read_csv(ARQUIVO, parse_dates=["order_date"])

    if not pd.api.types.is_datetime64_any_dtype(df["order_date"]):
        log.error("Coluna order_date não foi convertida para datetime.")
        raise TypeError("order_date deveria ser datetime64.")

    df["year_month"] = df["order_date"].dt.to_period("M")
    log.info("  %d linhas carregadas", len(df))
    return df



# KPI 1 | MRR Mensal

def calcular_mrr(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa vendas por mês e calcula os principais KPIs de receita.

    MRR  = soma das vendas no mês
    ARR  = MRR × 12  (projeção anual da receita corrente)
    ARPU = MRR ÷ clientes ativos (ticket médio por cliente)
    Crescimento MoM = quanto o MRR cresceu vs. mês anterior

    Nota sobre ARR × 12:
      Em SaaS real, ARR conta apenas contratos recorrentes anuais.
      Aqui tratamos todas as vendas como MRR e extrapolamos — é uma
      simplificação válida para o dataset do Kaggle, mas deve ser
      comunicada em uma apresentação real.
    """
    log.info("Calculando MRR mensal...")

    mrr = (
        df.groupby("year_month")
        .agg(
            mrr             =("sales",       "sum"),
            clientes_ativos =("customer_id", "nunique"),
            pedidos         =("order_id",    "nunique"),
            lucro           =("profit",      "sum"),
        )
        .reset_index()
    )

    mrr["arr"]        = mrr["mrr"] * 12
    mrr["arpu"]       = (mrr["mrr"] / mrr["clientes_ativos"]).round(2)
    mrr["margem_pct"] = (mrr["lucro"] / mrr["mrr"] * 100).round(2)

   
    mrr["crescimento_mom_pct"] = mrr["mrr"].pct_change().mul(100).round(2)


    mrr["year_month"] = mrr["year_month"].astype(str)

    log.info("  %d meses calculados", len(mrr))
    return mrr


# KPI 2 | Churn Rate

def calcular_churn(df: pd.DataFrame) -> pd.DataFrame:
    """
    Churn Rate = % de clientes que compraram no mês T mas não em T+1.

    Método:
      1. Cria uma tabela pivô: linhas = clientes, colunas = meses,
         valores = número de pedidos (0 se não comprou)
      2. Para cada par de meses consecutivos, identifica quem saiu
         (estava em T, não está em T+1) e calcula o percentual

    Limitação do método:
      Usa compra como proxy de atividade. Em SaaS real, churn é
      medido por cancelamento de contrato, aqui é uma aproximação.
    """
    log.info("Calculando Churn Rate mensal...")

    atividade = (
        df.groupby(["year_month", "customer_id"])
        .size()
        .reset_index(name="pedidos")
    )

    pivot = atividade.pivot_table(
        index="customer_id",
        columns="year_month",
        values="pedidos",
        fill_value=0,   # clientes que não compraram no mês recebem 0
    )

    meses = sorted(pivot.columns)

    if len(meses) < 2:
        log.warning("Dados insuficientes para calcular churn (< 2 meses).")
        return pd.DataFrame(columns=[
            "periodo", "clientes_ini", "clientes_fim",
            "novos", "sairam", "churn_pct", "retencao_pct",
        ])

    resultados = []
    for i in range(1, len(meses)):
        mes_anterior = meses[i - 1]
        mes_atual    = meses[i]

        ativos_antes = set(pivot.index[pivot[mes_anterior] > 0])
        ativos_agora = set(pivot.index[pivot[mes_atual]    > 0])

        sairam   = ativos_antes - ativos_agora  
        chegaram = ativos_agora - ativos_antes  

    
        churn = len(sairam) / len(ativos_antes) if ativos_antes else 0.0

        resultados.append({
            "periodo":      str(mes_atual),
            "clientes_ini": len(ativos_antes),
            "clientes_fim": len(ativos_agora),
            "novos":        len(chegaram),
            "sairam":       len(sairam),
            "churn_pct":    round(churn * 100, 2),
            "retencao_pct": round((1 - churn) * 100, 2),
        })

    churn_df = pd.DataFrame(resultados)
    log.info(
        "  Churn médio: %.2f%% | Retenção média: %.2f%%",
        churn_df["churn_pct"].mean(),
        churn_df["retencao_pct"].mean(),
    )
    return churn_df



# KPI 3 | LTV


def calcular_ltv(mrr_df: pd.DataFrame, churn_df: pd.DataFrame) -> dict:
    """
    LTV (Customer Lifetime Value) = ARPU ÷ Churn Rate mensal

    Raciocínio:
      Se um cliente gera $100/mês (ARPU) e 10% dos clientes saem por mês,
      a vida média esperada é 1/0.10 = 10 meses.
      LTV = $100 × 10 meses = $1.000
    """
    log.info("Calculando LTV...")

    arpu_medio = mrr_df["arpu"].mean()

    if churn_df.empty or churn_df["churn_pct"].mean() == 0:
        log.warning("Churn = 0 ou dados insuficientes - LTV não calculado.")
        return {
            "arpu_medio": round(arpu_medio, 2),
            "churn_pct":  0.0,
            "meses_vida": None,
            "ltv":        None,
        }

    churn_decimal = churn_df["churn_pct"].mean() / 100
    meses_vida    = 1 / churn_decimal
    ltv           = arpu_medio * meses_vida

    log.info(
        "  ARPU médio: $%.2f | Churn médio: %.2f%% | LTV: $%.2f",
        arpu_medio, churn_decimal * 100, ltv,
    )
    return {
        "arpu_medio": round(arpu_medio, 2),
        "churn_pct":  round(churn_decimal * 100, 2),
        "meses_vida": round(meses_vida, 1),
        "ltv":        round(ltv, 2),
    }


# Análise por Segmento


def por_segmento(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa receita, lucro e clientes por segmento.
    Segmentos típicos: SMB, Strategic, Enterprise, Government.
    """
    log.info("Analisando por segmento...")

    seg = (
        df.groupby("segment")
        .agg(
            receita =("sales",       "sum"),
            lucro   =("profit",      "sum"),
            clientes=("customer_id", "nunique"),
            pedidos =("order_id",    "nunique"),
        )
        .reset_index()
    )

    seg["margem_pct"] = (seg["lucro"]   / seg["receita"] * 100).round(2)
    seg["share_pct"]  = (seg["receita"] / seg["receita"].sum() * 100).round(2)
    seg["arpu"]       = (seg["receita"] / seg["clientes"]).round(2)

    return seg.sort_values("receita", ascending=False)


# Análise por produto

def por_produto(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa receita e margem por produto."""
    log.info("Analisando por produto...")

    prod = (
        df.groupby("product")
        .agg(
            receita =("sales",       "sum"),
            lucro   =("profit",      "sum"),
            clientes=("customer_id", "nunique"),
        )
        .reset_index()
    )

    prod["margem_pct"] = (prod["lucro"]   / prod["receita"] * 100).round(2)
    prod["share_pct"]  = (prod["receita"] / prod["receita"].sum() * 100).round(2)

    return prod.sort_values("receita", ascending=False)



# Gráficos


def grafico_mrr(mrr_df: pd.DataFrame) -> None:
    """Gráfico de linha: evolução do MRR mês a mês."""
    log.info("Gerando gráfico de MRR...")

    if mrr_df.empty:
        log.warning("  MRR vazio — gráfico não gerado.")
        return

    fig, ax = plt.subplots(figsize=(13, 5))

    x = list(range(len(mrr_df)))
    y = mrr_df["mrr"].values

    ax.plot(x, y, marker="o", linewidth=2.5, color="#2563EB", markersize=5)
    ax.fill_between(x, y, alpha=0.08, color="#2563EB")

    ax.set_title("MRR Mensal — Evolução da Receita", fontsize=14, fontweight="bold")
    ax.set_ylabel("Receita (USD)")
    ax.set_xticks(x)
    ax.set_xticklabels(mrr_df["year_month"].tolist(), rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.grid(True, alpha=0.25)

    plt.tight_layout()

    caminho = PASTA_GRAFICOS / "mrr_mensal.png"
    plt.savefig(caminho, dpi=150)
    log.info("  Salvo em %s", caminho)
    plt.show()
    plt.close(fig) 


def grafico_segmentos(seg_df: pd.DataFrame) -> None:
    """Dois gráficos lado a lado: receita e margem por segmento."""
    log.info("Gerando gráfico de segmentos...")

    if seg_df.empty:
        log.warning("  Segmentos vazio - gráfico não gerado.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Análise por Segmento de Cliente", fontsize=14, fontweight="bold")

    cores = ["#092C79", "#7C3AED", "#059669", "#DC2626"]
    # Garante que a paleta não quebre se houver mais de 4 segmentos
    cores = (cores * ((len(seg_df) // len(cores)) + 1))[: len(seg_df)]

    ax1.bar(seg_df["segment"], seg_df["receita"], color=cores)
    ax1.set_title("Receita Total por Segmento")
    ax1.set_ylabel("Receita (USD)")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax1.tick_params(axis="x", rotation=15)

    ax2.bar(seg_df["segment"], seg_df["margem_pct"], color=cores)
    ax2.set_title("Margem Bruta por Segmento (%)")
    ax2.set_ylabel("Margem (%)")
    ax2.tick_params(axis="x", rotation=15)

    plt.tight_layout()

    caminho = PASTA_GRAFICOS / "segmentos.png"
    plt.savefig(caminho, dpi=150)
    log.info("  Salvo em %s", caminho)
    plt.show()
    plt.close(fig)



def main() -> None:
    log.info("=" * 45)
    log.info("   Análises - SaaS Sales Analytics")
    log.info("=" * 45)

    try:
        df = carregar()
    except (FileNotFoundError, TypeError) as exc:
        log.critical("Não foi possível carregar os dados: %s", exc)
        sys.exit(1)

    mrr_df   = calcular_mrr(df)
    churn_df = calcular_churn(df)
    ltv      = calcular_ltv(mrr_df, churn_df)
    seg_df   = por_segmento(df)
    prod_df  = por_produto(df)


    if mrr_df.empty:
        log.warning("Nenhum dado de MRR disponível.")
    else:
        ultimo = mrr_df.iloc[-1]
        log.info("")
        log.info("KPIs — último mês (%s):", ultimo["year_month"])
        log.info("  MRR             : $%10.2f", float(ultimo["mrr"]))
        log.info("  ARR             : $%10.2f", float(ultimo["arr"]))
        log.info("  ARPU            : $%10.2f", float(ultimo["arpu"]))
        log.info("  Clientes ativos :  %9d",   int(ultimo["clientes_ativos"]))
        log.info("  Margem bruta    :  %8.2f%%", float(ultimo["margem_pct"]))

    log.info("")
    log.info("Médias históricas:")
    if not churn_df.empty:
        log.info("  Churn Rate mensal  : %6.2f%%", churn_df["churn_pct"].mean())
        log.info("  Retenção mensal    : %6.2f%%", churn_df["retencao_pct"].mean())
    if ltv["ltv"]:
        log.info("  LTV estimado       : $%8.2f", ltv["ltv"])
        log.info("  Vida média (meses) : %7.1f",  ltv["meses_vida"])

    log.info("")
    log.info("Receita por segmento:")
    log.info(
        "\n%s",
        seg_df[["segment", "receita", "margem_pct", "share_pct", "arpu"]].to_string(index=False),
    )

  
    mrr_df.to_csv(PASTA_CSV   / "mrr_mensal.csv",    index=False)
    churn_df.to_csv(PASTA_CSV / "churn_mensal.csv",  index=False)
    seg_df.to_csv(PASTA_CSV   / "por_segmento.csv",  index=False)
    prod_df.to_csv(PASTA_CSV  / "por_produto.csv",   index=False)
    log.info("CSVs salvos em data/processed/")

   
    log.info("Gerando gráficos...")
    grafico_mrr(mrr_df)
    grafico_segmentos(seg_df)

    log.info("Análise concluída")


if __name__ == "__main__":
    main()