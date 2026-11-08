# 03 — ETL Python + SQLite, PostgreSQL e MySQL

Projeto a partir dos exemplos de carga ANAC do material **Python – SGBDS**. Recebe registros de ocorrências ANAC (JSON ou CSV), seleciona sete colunas, valida, elimina repetidos por número da ocorrência e grava com **atualização incremental**. Por padrão usa SQLite, sem instalação de servidor.

## Teste rápido no Windows

```powershell
python etl.py
python etl.py --modo incremental
python -m unittest discover -s tests -v
```

Resultado: `dados/ocorrencias.db` e `dados/ultimo_relatorio.json`. Os dados de exemplo são inteiramente fictícios e pequenos.

**Com seus dados:** extraia o arquivo `V_OCORRENCIA_AMPLA.json` do material original e execute:

```powershell
python etl.py --origem "C:\caminho\V_OCORRENCIA_AMPLA.json" --modo incremental
```

`--modo completa` substitui a tabela apenas quando **todos os registros têm validação aprovada** (IDs repetidos são consolidados). Se houver registros inválidos, o sistema cancela a operação **antes de apagar qualquer dado**. Faça backup antes de executar esse modo. `incremental` não apaga registros antigos: insere novos e atualiza IDs existentes, ignorando registros inválidos.

## PostgreSQL ou MySQL (opcionais)

Primeiro configure um banco de testes **que você controla**. Dependências:

```powershell
python -m pip install -r requirements-opcionais.txt
```

Defina a variável `DATABASE_URL` no terminal, com usuário e senha do seu banco. Exemplo de formato (não é uma senha real):

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://USUARIO:SENHA@localhost:5432/banco_teste"
python etl.py --remoto
```

Para MySQL: `mysql+pymysql://USUARIO:SENHA@localhost:3306/banco_teste`.

**Segurança:** não coloque senhas dentro do código ou do GitHub. O SQL usa parâmetros. O modo remoto exige o banco já criado e credenciais válidas. Conectividade real com PostgreSQL/MySQL não foi testada neste pacote porque esses servidores não estão configurados.

## Validação

- CSV UTF-8/UTF-8 com BOM, com separador **vírgula ou ponto e vírgula** (incluindo exportação do Excel), ou JSON em formato de lista de objetos;
- CSV com cabeçalho duplicado, colunas essenciais ausentes ou linhas com quantidade errada de valores recebe validação específica;
- ocorrência precisa de número, data ISO (`AAAA-MM-DD`) e UF com duas letras;
- repetidos no mesmo arquivo: prevalece o último registro válido;
- carga realizada em transação (sem substituição parcial em caso de erro);
- lote sem registros válidos é recusado antes da atualização.
