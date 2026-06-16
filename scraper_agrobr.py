#!/usr/bin/env python3
"""
scraper_agrobr.py — Coleta dados de 40+ fontes agrícolas via agrobr
Salva em techobco_agropecuaria: preco_historico, safra_conab, producao_ibge, exportacao, credito_rural

Cron sugerido (2x/dia):
0 6,18 * * * /opt/painel-produtor/venv/bin/python3 /opt/painel-produtor/scraper_agrobr.py >> /var/log/painel-produtor/agrobr.log 2>&1

Criado: 15/06/2026
"""

import asyncio
import logging
import time
import math
import sys
from datetime import datetime, date
from decimal import Decimal

import mysql.connector

# ============================================================
# CONFIG
# ============================================================
DB_CONFIG = {
    "host": "199.167.147.66",
    "user": "techobco_agropecuaria",
    "password": "@precisao2203",
    "database": "techobco_agropecuaria",
    "charset": "utf8mb4",
    "connect_timeout": 30,
}

# Produtos por dataset
PRODUTOS_PRECO = [
    "soja", "milho", "cafe", "boi", "trigo", "algodao",
]

PRODUTOS_SAFRA = [
    "soja", "milho", "arroz", "feijao", "trigo", "algodao",
    "sorgo", "amendoim",
]

PRODUTOS_PRODUCAO = [
    "soja", "milho", "cafe", "arroz", "feijao", "trigo",
    "algodao", "cana-de-acucar", "laranja",
]

PRODUTOS_EXPORTACAO = [
    "soja", "milho", "cafe", "algodao", "acucar",
    "carne bovina", "carne de frango",
]

PRODUTOS_CREDITO = [
    "soja", "milho", "cafe", "arroz", "feijao", "trigo",
]

SAFRA_ATUAL = "2025/26"

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("agrobr")


# ============================================================
# DB HELPERS
# ============================================================
def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def ensure_tables(conn):
    """Cria tabelas se não existirem (idempotente)."""
    cursor = conn.cursor()
    ddl_statements = [
        """CREATE TABLE IF NOT EXISTS preco_historico (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS safra_conab (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS producao_ibge (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS exportacao (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS credito_rural (
            id INT AUTO_INCREMENT PRIMARY KEY,
            produto VARCHAR(60) NOT NULL,
            ano INT NOT NULL,
            uf VARCHAR(2) DEFAULT NULL,
            valor DECIMAL(16,2) DEFAULT NULL,
            qtd_contratos INT DEFAULT NULL,
            fonte VARCHAR(60) DEFAULT 'BCB/SICOR',
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_cred (produto, ano, uf)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS agrobr_coleta_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            dataset VARCHAR(40) NOT NULL,
            produto VARCHAR(60) DEFAULT NULL,
            registros INT DEFAULT 0,
            status ENUM('ok','erro','vazio') DEFAULT 'ok',
            mensagem TEXT DEFAULT NULL,
            duracao_seg DECIMAL(8,2) DEFAULT NULL,
            coletado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    ]
    for ddl in ddl_statements:
        cursor.execute(ddl)
    conn.commit()
    cursor.close()
    log.info("Tabelas verificadas/criadas com sucesso")


def log_coleta(conn, dataset, produto, registros, status, mensagem, duracao):
    """Registra resultado da coleta na tabela de log."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO agrobr_coleta_log (dataset, produto, registros, status, mensagem, duracao_seg)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (dataset, produto, registros, status, mensagem, round(duracao, 2)),
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        log.warning(f"Falha ao registrar log coleta: {e}")


def safe_float(val):
    """Converte valor pra float, retorna None se falhar."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def safe_int(val):
    """Converte valor pra int, retorna None se falhar."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def safe_str(val, max_len=None):
    """Converte pra string, trunca se necessário."""
    if val is None:
        return None
    s = str(val).strip()
    if max_len and len(s) > max_len:
        s = s[:max_len]
    return s if s else None


# ============================================================
# COLETORES
# ============================================================
async def coletar_precos(conn_unused):
    """Coleta preço diário via agrobr (CEPEA com fallback)."""
    from agrobr import datasets

    total = 0
    for produto in PRODUTOS_PRECO:
        t0 = time.time()
        conn = get_conn()
        try:
            df = await datasets.preco_diario(produto)
            if df is None or df.empty:
                log_coleta(conn, "preco_diario", produto, 0, "vazio", "DataFrame vazio", time.time() - t0)
                log.warning(f"  preco_diario({produto}): vazio")
                continue

            cursor = conn.cursor()
            inseridos = 0
            for _, row in df.iterrows():
                data_ref = row.get("data")
                valor = safe_float(row.get("valor"))
                if not data_ref or not valor:
                    continue

                # Normaliza data
                if hasattr(data_ref, "date"):
                    data_ref = data_ref.date()
                elif isinstance(data_ref, str):
                    data_ref = datetime.strptime(data_ref[:10], "%Y-%m-%d").date()

                praca = safe_str(row.get("praca"), 100) or ""
                unidade = safe_str(row.get("unidade"), 30)
                fonte = safe_str(row.get("fonte"), 60) or "CEPEA"
                metodologia = safe_str(row.get("metodologia"), 100)

                cursor.execute(
                    """INSERT INTO preco_historico (produto, praca, data_ref, valor, unidade, fonte, metodologia)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           valor = VALUES(valor),
                           unidade = VALUES(unidade),
                           fonte = VALUES(fonte),
                           metodologia = VALUES(metodologia),
                           atualizado_em = NOW()""",
                    (produto, praca, data_ref, valor, unidade, fonte, metodologia),
                )
                inseridos += 1

            conn.commit()
            cursor.close()
            total += inseridos
            log_coleta(conn, "preco_diario", produto, inseridos, "ok", None, time.time() - t0)
            log.info(f"  preco_diario({produto}): {inseridos} registros")

        except Exception as e:
            log_coleta(conn, "preco_diario", produto, 0, "erro", str(e)[:500], time.time() - t0)
            log.error(f"  preco_diario({produto}): ERRO — {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return total


async def coletar_safra(conn_unused):
    """Coleta estimativa de safra CONAB via agrobr."""
    from agrobr import datasets

    total = 0
    for produto in PRODUTOS_SAFRA:
        t0 = time.time()
        conn = get_conn()
        try:
            df = await datasets.estimativa_safra(produto, safra=SAFRA_ATUAL)
            if df is None or df.empty:
                log_coleta(conn, "safra", produto, 0, "vazio", "DataFrame vazio", time.time() - t0)
                log.warning(f"  safra({produto}): vazio")
                continue

            cursor = conn.cursor()
            inseridos = 0
            for _, row in df.iterrows():
                uf = safe_str(row.get("uf"), 2)
                safra = safe_str(row.get("safra"), 20) or SAFRA_ATUAL

                cursor.execute(
                    """INSERT INTO safra_conab
                       (produto, safra, uf, area_plantada, area_colhida, produtividade, producao, levantamento, fonte)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           area_plantada = VALUES(area_plantada),
                           area_colhida = VALUES(area_colhida),
                           produtividade = VALUES(produtividade),
                           producao = VALUES(producao),
                           levantamento = VALUES(levantamento),
                           fonte = VALUES(fonte),
                           atualizado_em = NOW()""",
                    (
                        produto,
                        safra,
                        uf,
                        safe_float(row.get("area_plantada")),
                        safe_float(row.get("area_colhida")),
                        safe_float(row.get("produtividade")),
                        safe_float(row.get("producao")),
                        safe_str(row.get("levantamento"), 60),
                        safe_str(row.get("fonte"), 60) or "CONAB",
                    ),
                )
                inseridos += 1

            conn.commit()
            cursor.close()
            total += inseridos
            log_coleta(conn, "safra", produto, inseridos, "ok", None, time.time() - t0)
            log.info(f"  safra({produto}): {inseridos} registros")

        except Exception as e:
            log_coleta(conn, "safra", produto, 0, "erro", str(e)[:500], time.time() - t0)
            log.error(f"  safra({produto}): ERRO — {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return total


async def coletar_producao(conn_unused):
    """Coleta produção anual IBGE via agrobr."""
    from agrobr import datasets

    total = 0
    for produto in PRODUTOS_PRODUCAO:
        t0 = time.time()
        conn = get_conn()
        try:
            df = await datasets.producao_anual(produto)
            if df is None or df.empty:
                log_coleta(conn, "producao", produto, 0, "vazio", "DataFrame vazio", time.time() - t0)
                log.warning(f"  producao({produto}): vazio")
                continue

            cursor = conn.cursor()
            inseridos = 0
            for _, row in df.iterrows():
                ano = safe_int(row.get("ano"))
                if not ano:
                    continue

                uf = safe_str(row.get("uf"), 2)

                cursor.execute(
                    """INSERT INTO producao_ibge
                       (produto, ano, uf, area_colhida, quantidade, rendimento, valor_producao, fonte)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           area_colhida = VALUES(area_colhida),
                           quantidade = VALUES(quantidade),
                           rendimento = VALUES(rendimento),
                           valor_producao = VALUES(valor_producao),
                           fonte = VALUES(fonte),
                           atualizado_em = NOW()""",
                    (
                        produto,
                        ano,
                        uf,
                        safe_float(row.get("area_colhida")),
                        safe_float(row.get("quantidade")),
                        safe_float(row.get("rendimento")),
                        safe_float(row.get("valor_producao")),
                        safe_str(row.get("fonte"), 60) or "IBGE/PAM",
                    ),
                )
                inseridos += 1

            conn.commit()
            cursor.close()
            total += inseridos
            log_coleta(conn, "producao", produto, inseridos, "ok", None, time.time() - t0)
            log.info(f"  producao({produto}): {inseridos} registros")

        except Exception as e:
            log_coleta(conn, "producao", produto, 0, "erro", str(e)[:500], time.time() - t0)
            log.error(f"  producao({produto}): ERRO — {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return total


async def coletar_exportacao(conn_unused):
    """Coleta dados de exportação ComexStat via agrobr."""
    from agrobr import datasets

    total = 0
    for produto in PRODUTOS_EXPORTACAO:
        t0 = time.time()
        conn = get_conn()
        try:
            df = await datasets.exportacao(produto)
            if df is None or df.empty:
                log_coleta(conn, "exportacao", produto, 0, "vazio", "DataFrame vazio", time.time() - t0)
                log.warning(f"  exportacao({produto}): vazio")
                continue

            cursor = conn.cursor()
            inseridos = 0
            for _, row in df.iterrows():
                ano = safe_int(row.get("ano"))
                if not ano:
                    continue

                mes = safe_int(row.get("mes"))
                pais = safe_str(row.get("pais_destino") or row.get("pais"), 100) or ""

                cursor.execute(
                    """INSERT INTO exportacao
                       (produto, ano, mes, peso_kg, valor_usd, pais_destino, fonte)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           peso_kg = VALUES(peso_kg),
                           valor_usd = VALUES(valor_usd),
                           fonte = VALUES(fonte),
                           atualizado_em = NOW()""",
                    (
                        produto,
                        ano,
                        mes,
                        safe_float(row.get("peso_kg") or row.get("peso")),
                        safe_float(row.get("valor_usd") or row.get("valor")),
                        pais,
                        safe_str(row.get("fonte"), 60) or "ComexStat",
                    ),
                )
                inseridos += 1

            conn.commit()
            cursor.close()
            total += inseridos
            log_coleta(conn, "exportacao", produto, inseridos, "ok", None, time.time() - t0)
            log.info(f"  exportacao({produto}): {inseridos} registros")

        except Exception as e:
            log_coleta(conn, "exportacao", produto, 0, "erro", str(e)[:500], time.time() - t0)
            log.error(f"  exportacao({produto}): ERRO — {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return total


async def coletar_credito(conn_unused):
    """Coleta crédito rural BCB/SICOR via agrobr."""
    from agrobr import datasets

    total = 0
    for produto in PRODUTOS_CREDITO:
        t0 = time.time()
        conn = get_conn()
        try:
            df = await datasets.credito_rural(produto)
            if df is None or df.empty:
                log_coleta(conn, "credito", produto, 0, "vazio", "DataFrame vazio", time.time() - t0)
                log.warning(f"  credito({produto}): vazio")
                continue

            cursor = conn.cursor()
            inseridos = 0
            for _, row in df.iterrows():
                ano = safe_int(row.get("ano"))
                if not ano:
                    continue

                uf = safe_str(row.get("uf"), 2)

                cursor.execute(
                    """INSERT INTO credito_rural
                       (produto, ano, uf, valor, qtd_contratos, fonte)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           valor = VALUES(valor),
                           qtd_contratos = VALUES(qtd_contratos),
                           fonte = VALUES(fonte),
                           atualizado_em = NOW()""",
                    (
                        produto,
                        ano,
                        uf,
                        safe_float(row.get("valor")),
                        safe_int(row.get("qtd_contratos") or row.get("contratos")),
                        safe_str(row.get("fonte"), 60) or "BCB/SICOR",
                    ),
                )
                inseridos += 1

            conn.commit()
            cursor.close()
            total += inseridos
            log_coleta(conn, "credito", produto, inseridos, "ok", None, time.time() - t0)
            log.info(f"  credito({produto}): {inseridos} registros")

        except Exception as e:
            log_coleta(conn, "credito", produto, 0, "erro", str(e)[:500], time.time() - t0)
            log.error(f"  credito({produto}): ERRO — {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return total


# ============================================================
# MAIN
# ============================================================
async def main():
    inicio = time.time()
    log.info("=" * 60)
    log.info("INICIO COLETA AGROBR")
    log.info("=" * 60)

    conn = get_conn()
    ensure_tables(conn)
    conn.close()

    resultados = {}

    log.info("[1/5] Precos diarios (CEPEA)...")
    conn = get_conn()
    resultados["precos"] = await coletar_precos(conn)
    conn.close()

    log.info("[2/5] Safra CONAB...")
    conn = get_conn()
    resultados["safra"] = await coletar_safra(conn)
    conn.close()

    log.info("[3/5] Producao IBGE...")
    conn = get_conn()
    resultados["producao"] = await coletar_producao(conn)
    conn.close()

    log.info("[4/5] Exportacoes...")
    conn = get_conn()
    resultados["exportacao"] = await coletar_exportacao(conn)
    conn.close()

    log.info("[5/5] Credito rural...")
    conn = get_conn()
    resultados["credito"] = await coletar_credito(conn)
    conn.close()

    duracao = time.time() - inicio
    total = sum(resultados.values())

    log.info("=" * 60)
    log.info(f"COLETA FINALIZADA em {duracao:.1f}s")
    for k, v in resultados.items():
        log.info(f"  {k}: {v} registros")
    log.info(f"  TOTAL: {total} registros")
    log.info("=" * 60)

    return total


if __name__ == "__main__":
    try:
        total = asyncio.run(main())
        sys.exit(0 if total > 0 else 1)
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuario")
        sys.exit(130)
    except Exception as e:
        log.critical(f"ERRO FATAL: {e}", exc_info=True)
        sys.exit(1)
