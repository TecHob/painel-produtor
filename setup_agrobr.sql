-- ============================================================
-- SETUP AGROBR — Tabelas para dados de 40 fontes agrícolas
-- techobco_agropecuaria @ 199.167.147.66
-- Criado em 15/06/2026
-- ============================================================

-- 1. Histórico de preços diários (CEPEA via agrobr)
CREATE TABLE IF NOT EXISTS preco_historico (
    id INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(60) NOT NULL,
    praca VARCHAR(100) DEFAULT NULL,
    data_ref DATE NOT NULL,
    valor DECIMAL(12,2) NOT NULL,
    unidade VARCHAR(30) DEFAULT NULL,
    fonte VARCHAR(60) DEFAULT 'CEPEA',
    metodologia VARCHAR(100) DEFAULT NULL,
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_preco (produto, praca, data_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Estimativa de safra (CONAB via agrobr)
CREATE TABLE IF NOT EXISTS safra_conab (
    id INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(60) NOT NULL,
    safra VARCHAR(20) NOT NULL,
    uf VARCHAR(2) DEFAULT NULL,
    area_plantada DECIMAL(14,2) DEFAULT NULL,
    area_colhida DECIMAL(14,2) DEFAULT NULL,
    produtividade DECIMAL(14,2) DEFAULT NULL,
    producao DECIMAL(14,2) DEFAULT NULL,
    levantamento VARCHAR(60) DEFAULT NULL,
    fonte VARCHAR(60) DEFAULT 'CONAB',
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_safra (produto, safra, uf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Produção anual (IBGE via agrobr)
CREATE TABLE IF NOT EXISTS producao_ibge (
    id INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(60) NOT NULL,
    ano INT NOT NULL,
    uf VARCHAR(2) DEFAULT NULL,
    area_colhida DECIMAL(14,2) DEFAULT NULL,
    quantidade DECIMAL(14,2) DEFAULT NULL,
    rendimento DECIMAL(14,2) DEFAULT NULL,
    valor_producao DECIMAL(16,2) DEFAULT NULL,
    fonte VARCHAR(60) DEFAULT 'IBGE/PAM',
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_prod (produto, ano, uf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Exportações (ComexStat via agrobr)
CREATE TABLE IF NOT EXISTS exportacao (
    id INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(60) NOT NULL,
    ano INT NOT NULL,
    mes INT DEFAULT NULL,
    peso_kg DECIMAL(18,2) DEFAULT NULL,
    valor_usd DECIMAL(16,2) DEFAULT NULL,
    pais_destino VARCHAR(100) DEFAULT NULL,
    fonte VARCHAR(60) DEFAULT 'ComexStat',
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_exp (produto, ano, mes, pais_destino)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Crédito rural (BCB/SICOR via agrobr)
CREATE TABLE IF NOT EXISTS credito_rural (
    id INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(60) NOT NULL,
    ano INT NOT NULL,
    uf VARCHAR(2) DEFAULT NULL,
    valor DECIMAL(16,2) DEFAULT NULL,
    qtd_contratos INT DEFAULT NULL,
    fonte VARCHAR(60) DEFAULT 'BCB/SICOR',
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_cred (produto, ano, uf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Metadados de coleta (controle do scraper)
CREATE TABLE IF NOT EXISTS agrobr_coleta_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    dataset VARCHAR(40) NOT NULL,
    produto VARCHAR(60) DEFAULT NULL,
    registros INT DEFAULT 0,
    status ENUM('ok','erro','vazio') DEFAULT 'ok',
    mensagem TEXT DEFAULT NULL,
    duracao_seg DECIMAL(8,2) DEFAULT NULL,
    coletado_em DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Indices extras para queries do agente
CREATE INDEX IF NOT EXISTS idx_preco_produto_data ON preco_historico(produto, data_ref DESC);
CREATE INDEX IF NOT EXISTS idx_safra_produto ON safra_conab(produto, safra);
CREATE INDEX IF NOT EXISTS idx_prod_produto_ano ON producao_ibge(produto, ano DESC);
CREATE INDEX IF NOT EXISTS idx_exp_produto ON exportacao(produto, ano DESC, mes DESC);
