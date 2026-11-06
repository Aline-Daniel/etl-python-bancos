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
