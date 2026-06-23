# CorpusForge

Ferramenta para download e conversão de referências bibliográficas extraídas de respostas de LLMs.

O script extrai URLs de um arquivo de resposta (markdown, PDF ou DOCX), baixa o conteúdo de cada referência e converte para markdown, salvando o resultado em uma pasta de documentos.

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
# Processar arquivo markdown
python main.py answers/meu_arquivo.md

# Processar arquivo PDF
python main.py answers/artigo.pdf

# Processar arquivo DOCX
python main.py answers/relatorio.docx

# Processar múltiplos arquivos de diferentes formatos
python main.py answers/resposta.md answers/artigo.pdf answers/relatorio.docx

# Reprocessar apenas URLs que falharam anteriormente
python main.py --retry-errors answers/meu_arquivo.md

# Usar JSON de referências pré-extraído (pula extração LLM)
python main.py --references-json references/references_lmStudio_20260621_164208.json

# Controlar paralelismo dos downloads (padrão: 4 threads)
python main.py --max-workers 8 answers/meu_arquivo.md

# Especificar arquivo de registro customizado
python main.py --register ./register/meu_registro.json answers/meu_arquivo.md
```

### Barra de Progresso

Durante o download das referências, uma barra de progresso é exibida:

```
Baixando referências: 100%|██████████| 10/10 [00:31<00:00,  3.12s/ref]
```

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `LLM_BASE_URL` | `http://localhost:1234/v1/` | URL do servidor LLM |
| `LLM_MODEL` | `openai/gpt-oss-20b` | Modelo a ser utilizado |
| `REGISTER_FILE` | `./register/register.json` | Caminho do arquivo de registro |

## Estrutura do Projeto

```
CorpusForge/
├── main.py                         # Ponto de entrada
├── src/
│   ├── logging_config.py           # Configuração de logging
│   └── services/
│       ├── file_converter.py       # Download e conversão de URLs
│       ├── llm_service.py          # Serviço de LLM (OpenAI/Ollama)
│       └── reference_extractor.py  # Extração de referências via LLM
├── answers/                        # Arquivos de resposta (entrada)
├── documents/                      # Documentos baixados (saída)
├── references/                     # Referências extraídas JSON
└── register/                       # Registro de processamento
```

## Formatos Suportados

| Formato | Extensões | Descrição |
|---------|-----------|-----------|
| Markdown | `.md`, `.markdown` | Leitura direta |
| PDF | `.pdf` | Conversão via PyMuPDF4LLM |
| Word | `.docx` | Extração via python-docx |

> **Nota:** Arquivos `.doc` (formato antigo) não são suportados. Converta para `.docx` antes de usar.

## Formato dos Arquivos

### JSON de Referências (pré-extraído)

JSON com referências extraídas anteriormente, usado com `--references-json`:

```json
{
  "answer": "answers/arquivo_original.pdf",
  "references": [
    {
      "id": 1,
      "url": "https://exemplo.com/documento",
      "paragraph": "Parágrafo completo onde a referência aparece."
    },
    {
      "id": 2,
      "url": "https://exemplo.com/outro",
      "paragraph": "Outro parágrafo com referência."
    }
  ]
}
```

> **Nota:** O campo `answer` é obrigatório para associar o registro ao arquivo original.

### Arquivo de Resposta (entrada)

Markdown, PDF ou DOCX com lista de referências numeradas e URLs:

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

## Funcionalidades

- **Múltiplos formatos de entrada:** Markdown, PDF e DOCX
- **Download paralelo:** Threads configuráveis via `--max-workers`
- **Barra de progresso:** Acompanhamento visual durante downloads
- **Retry seletivo:** Reprocessamento de erros recuperáveis (429, timeout, 403)
- **Referências pré-extraídas:** Pular extração LLM com `--references-json`
- **Deduplicação automática:** Referências duplicadas entre chunks são ignoradas
- **Validação de URLs:** Rejeita schemes inválidos (file://, javascript:, etc.)
- **Logging estruturado:** Mensagens com timestamp e nível de severidade
- **Registro atômico:** Escrita segura do register (write-then-rename)
