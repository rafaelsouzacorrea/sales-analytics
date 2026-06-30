-- schema.sql — SaaS Sales Analytics
-- Define a estrutura do banco ANTES de rodar o ETL.

-- Como usar:
--   psql -U postgres -d saas_analytics -f schema.sql

-- Garante que o banco existe
-- CREATE DATABASE saas_analytics;
-- \c saas_analytics


DROP TABLE IF EXISTS vendas CASCADE;

CREATE TABLE vendas (
    row_id          INTEGER         PRIMARY KEY,

    -- Identificadores de pedido e cliente
    order_id        VARCHAR(50)     NOT NULL,
    customer_id     VARCHAR(50)     NOT NULL,
    customer_name   VARCHAR(150)    NOT NULL,

    -- Data da venda
    order_date      DATE            NOT NULL,
    date_key        INTEGER,

    -- Dados de contato e localização
    contact_name    VARCHAR(150),
    country         VARCHAR(100),
    city            VARCHAR(100),
    region          VARCHAR(100),
    subregion       VARCHAR(100),

    -- Segmentação de negócio
    industry        VARCHAR(100),
    segment         VARCHAR(50)     CHECK (segment IN ('SMB', 'Strategic', 'Enterprise', 'Government')),

    -- Produto
    product         VARCHAR(150)    NOT NULL,
    license         VARCHAR(100),

    -- Valores financeiros
    sales           NUMERIC(12, 2)  NOT NULL    CHECK (sales >= 0),
    quantity        INTEGER         NOT NULL    CHECK (quantity > 0),
    discount        NUMERIC(5, 4)   NOT NULL    DEFAULT 0   CHECK (discount BETWEEN 0 AND 1),
    profit          NUMERIC(12, 2)  NOT NULL,

    -- Colunas derivadas de data
    year            SMALLINT        NOT NULL,
    month           SMALLINT        NOT NULL    CHECK (month BETWEEN 1 AND 12),
    quarter         SMALLINT        NOT NULL    CHECK (quarter BETWEEN 1 AND 4),
    year_month      VARCHAR(7)      NOT NULL  
);

-- Comentário na tabela
COMMENT ON TABLE vendas IS 'Transações de vendas SaaS importadas do CSV Kaggle via ETL';



-- Índice de data: usado em quase todas as queries de série temporal
CREATE INDEX idx_vendas_order_date   ON vendas (order_date);

-- Índice de período: usado nos GROUP BY de MRR mensal
CREATE INDEX idx_vendas_year_month   ON vendas (year_month);

-- Índice de cliente: usado em COUNT(DISTINCT customer_id)
CREATE INDEX idx_vendas_customer_id  ON vendas (customer_id);

-- Índice de segmento: usado nas queries de análise por segmento
CREATE INDEX idx_vendas_segment      ON vendas (segment);

-- Índice de produto: usado nas queries de top produtos
CREATE INDEX idx_vendas_product      ON vendas (product);



-- VIEW ANALÍTICA

CREATE OR REPLACE VIEW vw_receita_mensal AS
SELECT
    year_month,
    year,
    month,
    SUM(sales)                                                       AS mrr,
    SUM(sales) * 12                                                  AS arr,
    COUNT(DISTINCT customer_id)                                      AS clientes_ativos,
    ROUND(
        SUM(sales) / NULLIF(COUNT(DISTINCT customer_id), 0),
        2
    )                                                                AS arpu,
    SUM(profit)                                                      AS lucro_bruto,
    ROUND(
        SUM(profit) / NULLIF(SUM(sales), 0) * 100,
        2
    )                                                                AS margem_pct,
    COUNT(DISTINCT order_id)                                         AS pedidos
FROM vendas
GROUP BY year_month, year, month;

COMMENT ON VIEW vw_receita_mensal IS
    'Agrega vendas por mês: MRR, ARR, ARPU, margem e pedidos';