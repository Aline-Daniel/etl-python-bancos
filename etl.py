"""ETL seguro de ocorrências ANAC: JSON/CSV -> SQLite / PostgreSQL / MySQL.

Em SQLite funciona só com a biblioteca padrão. Os outros bancos são opcionais.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
KEYS = {
    'numero_ocorrencia': ('Numero_da_Ocorrencia', 'numero_ocorrencia'),
    'classificacao': ('Classificacao_da_Ocorrência', 'Classificacao_da_Ocorrencia', 'classificacao'),
    'data_ocorrencia': ('Data_da_Ocorrencia', 'data_ocorrencia'),
    'municipio': ('Municipio', 'municipio'),
    'uf': ('UF', 'uf'),
    'regiao': ('Regiao', 'regiao'),
    'fabricante': ('Nome_do_Fabricante', 'fabricante'),
}
FIELDS = list(KEYS)
CREATE_SQL = """CREATE TABLE IF NOT EXISTS ocorrencias_anac (
    numero_ocorrencia VARCHAR(64) PRIMARY KEY,
    classificacao VARCHAR(200) NOT NULL,
    data_ocorrencia VARCHAR(10) NOT NULL,
    municipio VARCHAR(200) NOT NULL,
    uf VARCHAR(2) NOT NULL,
    regiao VARCHAR(100) NOT NULL,
    fabricante VARCHAR(200) NOT NULL,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""
UPSERT_SQLITE_POSTGRES = """INSERT INTO ocorrencias_anac
 (numero_ocorrencia,classificacao,data_ocorrencia,municipio,uf,regiao,fabricante)
 VALUES (:numero_ocorrencia,:classificacao,:data_ocorrencia,:municipio,:uf,:regiao,:fabricante)
 ON CONFLICT(numero_ocorrencia) DO UPDATE SET
 classificacao=excluded.classificacao,data_ocorrencia=excluded.data_ocorrencia,
 municipio=excluded.municipio,uf=excluded.uf,regiao=excluded.regiao,
 fabricante=excluded.fabricante,atualizado_em=CURRENT_TIMESTAMP"""
UPSERT_MYSQL = """INSERT INTO ocorrencias_anac
 (numero_ocorrencia,classificacao,data_ocorrencia,municipio,uf,regiao,fabricante)
 VALUES (:numero_ocorrencia,:classificacao,:data_ocorrencia,:municipio,:uf,:regiao,:fabricante)
 ON DUPLICATE KEY UPDATE classificacao=VALUES(classificacao),
 data_ocorrencia=VALUES(data_ocorrencia),municipio=VALUES(municipio),
 uf=VALUES(uf),regiao=VALUES(regiao),fabricante=VALUES(fabricante),
 atualizado_em=CURRENT_TIMESTAMP"""


def ler_arquivo(arquivo: Path) -> list[dict[str, Any]]:
    if not arquivo.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {arquivo}")
    if arquivo.suffix.lower() == '.json':
        with arquivo.open(encoding='utf-8-sig') as file:
            rows = json.load(file)
        if not isinstance(rows, list):
            raise ValueError('O JSON precisa conter uma lista de objetos.')
        return rows
    if arquivo.suffix.lower() == '.csv':
        with arquivo.open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))
    raise ValueError('Formato não suportado. Use .json ou .csv.')


def campo(linha: dict[str, Any], nomes: tuple[str, ...]) -> str:
    for name in nomes:
        if name in linha:
            raw = linha[name]
            return '' if raw is None else str(raw).strip()
    return ''


def normalizar(linha: dict[str, Any]) -> dict[str, str]:
    if not isinstance(linha, dict):
        raise ValueError('Registro não é objeto.')
    d = {k:campo(linha, names) for k, names in KEYS.items()}
    number = d['numero_ocorrencia']
    if not number or len(number) > 64:
        raise ValueError('Número da ocorrência ausente ou inválido.')
    try:
        d['data_ocorrencia'] = date.fromisoformat(d['data_ocorrencia']).isoformat()
    except ValueError as exc:
        raise ValueError(f"Data inválida para ocorrência {number}.") from exc
    d['uf'] = d['uf'].upper()
    if not re.fullmatch('[A-Z]{2}', d['uf']):
        raise ValueError(f"UF inválida para ocorrência {number}.")
    for key, limit in [('classificacao',200),('municipio',200),('regiao',100),('fabricante',200)]:
        if len(d[key]) > limit:
            d[key] = d[key][:limit]
    return d


def preparar(linhas: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, int]]:
    items: dict[str, dict[str, str]] = {}
    invalidos = 0
    duplicados = 0
    for linha in linhas:
        try:
            d = normalizar(linha)
        except ValueError:
            invalidos += 1
            continue
        if d['numero_ocorrencia'] in items:
            duplicados += 1
        items[d['numero_ocorrencia']] = d  # vence o último registro válido por ID
    return list(items.values()), dict(lidos=len(linhas), validos=len(items), invalidos=invalidos, duplicados=duplicados)


def gravar_sqlite(registros: list[dict[str, str]], database: Path, modo: str) -> int:
    database.parent.mkdir(parents=True, exist_ok=True)
    # Atomicidade: um erro não deixa a tabela parcialmente atualizada.
    with sqlite3.connect(database, timeout=30) as con:
        con.execute(CREATE_SQL)
        if modo == 'completa':
            con.execute('DELETE FROM ocorrencias_anac')
        con.executemany(UPSERT_SQLITE_POSTGRES, registros)
        return con.execute('SELECT COUNT(*) FROM ocorrencias_anac').fetchone()[0]


def gravar_remoto(registros: list[dict[str, str]], url: str, modo: str) -> int:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError('Instale sqlalchemy e o driver de seu banco antes de usar conexão remota.') from exc
    engine = create_engine(url, pool_pre_ping=True)
    dialect = engine.dialect.name
    if dialect not in ('postgresql','mysql'):
        raise ValueError('Só PostgreSQL e MySQL são aceitos como destino remoto.')
    try:
        with engine.begin() as conn:
            conn.execute(text(CREATE_SQL))
            if modo == 'completa':
                conn.execute(text('DELETE FROM ocorrencias_anac'))
            if registros:
                conn.execute(text(UPSERT_MYSQL if dialect == 'mysql' else UPSERT_SQLITE_POSTGRES), registros)
            return int(conn.execute(text('SELECT COUNT(*) FROM ocorrencias_anac')).scalar_one())
    finally:
        engine.dispose()


def executar(arquivo: Path, database: Path, modo: str = 'incremental', database_url: str | None = None) -> dict[str, Any]:
    if modo not in ('incremental','completa'):
        raise ValueError('Modo inválido.')
    linhas = ler_arquivo(arquivo)
    registros, resumo = preparar(linhas)
    # Proteção: nunca apagar tabela se o arquivo não tiver registros válidos.
    if not registros:
        raise ValueError('Nenhum registro válido. Nada foi alterado no banco.')
    total = gravar_remoto(registros, database_url, modo) if database_url else gravar_sqlite(registros, database, modo)
    return {**resumo, 'modo': modo, 'registros_no_banco': total, 'data_execucao': datetime.now().isoformat(timespec='seconds')}


def main():
    parser = argparse.ArgumentParser(description='ETL de ocorrências ANAC com carga incremental')
    parser.add_argument('--origem', type=Path, default=ROOT/'dados'/'ocorrencias_exemplo.json')
    parser.add_argument('--db', type=Path, default=ROOT/'dados'/'ocorrencias.db')
    parser.add_argument('--modo', choices=['incremental','completa'], default='incremental')
    parser.add_argument('--remoto', action='store_true', help='Usar DATABASE_URL de variável ambiente')
    parser.add_argument('--relatorio', type=Path, default=ROOT/'dados'/'ultimo_relatorio.json')
    a = parser.parse_args()
    try:
        url = os.getenv('DATABASE_URL') if a.remoto else None
        if a.remoto and not url:
            raise ValueError('Defina DATABASE_URL no ambiente. Nunca coloque senha no código.')
        resumo = executar(a.origem, a.db, a.modo, url)
        a.relatorio.parent.mkdir(parents=True, exist_ok=True)
        a.relatorio.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
    except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Falha: {exc}\n')


if __name__ == '__main__':
    main()
