# CorpusForge

Ferramenta para download e conversão de referências bibliográficas extraídas de respostas de LLMs.

O script extrai URLs de um arquivo markdown de resposta, baixa o conteúdo de cada referência e converte para markdown, salvando o resultado em uma pasta de documentos.

## Pré-requisitos

- Python 3.10+
- Servidor LLM local (ex: LM Studio) ou API OpenAI compatível

## Instalação

```bash
# Clonar o repositório
git clone https://github.com/menezs/CorpusForge.git
cd CorpusForge

# Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Instalar dependências
pip install -r requirements.txt

# Instalar navegador do Playwright (para páginas JavaScript)
python -m playwright install chromium

# Configurar variáveis de ambiente
cp .env.example .env
# Edite .env com suas configurações
```

## Uso

```bash
# Processar um ou mais arquivos de resposta
python main.py answers/meu_arquivo.md

# Processar múltiplos arquivos
python main.py answers/arquivo1.md answers/arquivo2.md

# Reprocessar apenas URLs que falharam anteriormente
python main.py --retry-errors answers/meu_arquivo.md

# Especificar arquivo de registro customizado
python main.py --register ./register/meu_registro.json answers/meu_arquivo.md
```

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `LLM_BASE_URL` | `http://localhost:1234/v1/` | URL do servidor LLM |
| `LLM_MODEL` | `google/gemma-4-e4b` | Modelo a ser utilizado |
| `REGISTER_FILE` | `./register/register.json` | Caminho do arquivo de registro |

## Estrutura do Projeto

```
CorpusForge/
├── main.py                         # Ponto de entrada
├── src/
│   └── services/
│       ├── file_converter.py       # Download e conversão de URLs
│       ├── llm_service.py          # Serviço de LLM (OpenAI/Ollama)
│       └── reference_extractor.py  # Extração de referências via LLM
├── answers/                        # Arquivos de resposta (entrada)
├── documents/                      # Documentos baixados (saída)
├── references/                     # Referências extraídas JSON
└── register/                       # Registro de processamento
```

## Formato dos Arquivos

### Arquivo de Resposta (entrada)

Markdown com lista de referências numeradas e URLs:

```markdown
[1] Título do Documento
https://exemplo.com/documento

[2] Outro Documento
https://exemplo.com/outro
```

### Registro de Processamento (saída)

JSON com status do download de cada referência:

```json
[
  {
    "answer": "answers/arquivo.md",
    "documents": ["documents/arquivo_doc_1.md"],
    "errors": [
      {
        "url": "https://exemplo.com/404",
        "error_type": "ValueError",
        "error_message": "Página não encontrada (404)",
        "reference_id": 3
      }
    ]
  }
]
```
