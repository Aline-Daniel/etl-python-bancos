import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from etl import executar, preparar, normalizar


class TestETL(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name)/'anac.db'
        self.sample = Path(__file__).resolve().parents[1] / 'dados/ocorrencias_exemplo.json'

    def tearDown(self): self.tmp.cleanup()

    def test_normaliza_linha(self):
        d=normalizar({'Numero_da_Ocorrencia':'A1','Data_da_Ocorrencia':'2024-10-10','UF':'sp'})
        self.assertEqual(d['uf'], 'SP')
        self.assertEqual(d['numero_ocorrencia'],'A1')

    def test_pula_invalidos_e_deduplica(self):
        origem=json.loads(self.sample.read_text())
        items, report=preparar(origem + [{'UF':'SP'}])
        self.assertEqual(report, dict(lidos=5,validos=3,invalidos=1,duplicados=1))
        self.assertEqual(items[1]['fabricante'], 'Fabricante B (revisão)')

    def test_csv_ponto_e_virgula_compativel_com_excel(self):
        arq = Path(self.tmp.name) / 'origem_excel.csv'
        arq.write_text(
            'Numero_da_Ocorrencia;Classificacao_da_Ocorrencia;Data_da_Ocorrencia;Municipio;UF;Regiao;Nome_do_Fabricante\n'
            'A-100;Incidente;2025-01-10;Campinas;sp;Sudeste;Fabricante de teste\n',
            encoding='utf-8-sig'
        )
        resumo = executar(arq, self.db)
        self.assertEqual(resumo['validos'], 1)
        self.assertEqual(resumo['invalidos'], 0)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(
                con.execute('SELECT uf FROM ocorrencias_anac WHERE numero_ocorrencia=?', ('A-100',)).fetchone()[0],
                'SP'
            )

    def test_csv_colunas_duplicadas_ou_essenciais_ausentes(self):
        from etl import ler_arquivo
        arq = Path(self.tmp.name) / 'cabecalho.csv'
        arq.write_text('Numero_da_Ocorrencia;Numero_da_Ocorrencia;Data_da_Ocorrencia;UF\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicadas'):
            ler_arquivo(arq)
        arq.write_text('Nome;Data_da_Ocorrencia;UF\nTeste;2025-01-10;SP\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'coluna obrigatória'):
            ler_arquivo(arq)

    def test_csv_linha_com_colunas_a_mais_ou_a_menos(self):
        from etl import ler_arquivo
        arq = Path(self.tmp.name) / 'colunas.csv'
        arq.write_text(
            'Numero_da_Ocorrencia;Data_da_Ocorrencia;UF;Municipio\n'
            '1;2025-01-10;SP;Campinas;EXTRA\n'
            '2;2025-01-11;RJ\n',
            encoding='utf-8'
        )
        linhas = ler_arquivo(arq)
        registros, resumo = preparar(linhas)
        self.assertEqual(registros, [])
        self.assertEqual(resumo['invalidos'], 2)

    def test_carga_completa_recusa_parcialmente_invalido_sem_apagar(self):
        executar(self.sample, self.db)
        origem = json.loads(self.sample.read_text(encoding='utf-8'))
        arq = Path(self.tmp.name) / 'parcial.json'
        arq.write_text(json.dumps([origem[0], {'UF': 'xx'}]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Carga completa cancelada'):
            executar(arq, self.db, 'completa')
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM ocorrencias_anac').fetchone()[0], 3)
            self.assertEqual(
                con.execute('SELECT fabricante FROM ocorrencias_anac WHERE numero_ocorrencia=?', ('1002',)).fetchone()[0],
                'Fabricante B (revisão)'
            )

    def test_incremental_idempotente(self):
        result=executar(self.sample,self.db)
        self.assertEqual(result['registros_no_banco'],3)
        self.assertEqual(executar(self.sample,self.db)['registros_no_banco'],3)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('select fabricante from ocorrencias_anac where numero_ocorrencia="1002"').fetchone()[0], 'Fabricante B (revisão)')

    def test_carga_completa(self):
        executar(self.sample,self.db)
        d=json.loads(self.sample.read_text())[:1]
        arq=Path(self.tmp.name)/'um.json';arq.write_text(json.dumps(d))
        self.assertEqual(executar(arq,self.db, 'completa')['registros_no_banco'],1)

    def test_arquivo_invalido_nao_apaga_tabela(self):
        executar(self.sample,self.db)
        arq=Path(self.tmp.name)/'vazio.json';arq.write_text('[]')
        with self.assertRaises(ValueError): executar(arq,self.db,'completa')
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('select count(*) from ocorrencias_anac').fetchone()[0],3)


if __name__ == '__main__': unittest.main()
