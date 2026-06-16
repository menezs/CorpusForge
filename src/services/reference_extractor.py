import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Union
from .llm_service import LLMService


class ReferenceExtractor:
    MAX_TOKENS = 16000
    CHUNK_TOKENS = 500
    PROMPT_TOKENS = 2000

    DEFAULT_PROMPT = """Você é um sistema especializado em extração estruturada de referências acadêmicas.

## Objetivo

Extrair TODAS as referências presentes no texto, incluindo:

* URLs (http/https)
* DOIs (mesmo sem link explícito)
* Citações com link embutido (inline)

---

## Regras de extração

1. Cada referência deve ser extraída individualmente.
2. DOIs devem ser normalizados para formato URL:

   * Ex: `10.1145/123456` → `https://doi.org/10.1145/123456`
3. O campo `paragraph` deve conter:

   * O **parágrafo completo** onde a referência aparece
   * Preservando o texto original (sem cortes ou resumos)
5. Considere citações inline dentro de frases, parênteses ou notas.
6. Ignore referências incompletas que não possam ser convertidas em URL válida.

---

## Formato de saída

* Retorne **apenas JSON válido**
* NÃO inclua explicações, comentários ou texto adicional

### Estrutura:

[
{{
'id': 1,
'url': 'https://exemplo.com',
'paragraph': 'Parágrafo completo onde a referência aparece.'
}}
]

---

## Validações obrigatórias

* O JSON deve ser válido (sem vírgulas extras, aspas incorretas, etc.)
* Nenhum campo pode estar vazio
* Preservar encoding UTF-8

---

## Texto de entrada

{chunk}

"""

    def __init__(
        self,
        llm_service: LLMService,
        output_dir: str = "./references",
        model: str = "gpt-oss:20b"
    ):
        self._llm_service = llm_service
        self._output_dir = Path(output_dir)
        self._model = model
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _split_into_chunks(self, text: str) -> List[str]:
        chunks = []
        paragraphs = text.split("\n\n")
        current_chunk = ""
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._estimate_tokens(para)

            if current_tokens + para_tokens > self.CHUNK_TOKENS and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
                current_tokens = 0

            current_chunk += para + "\n\n"
            current_tokens += para_tokens

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _extract_references(self, chunk: str) -> List[Dict[str, Any]]:
        prompt = self.DEFAULT_PROMPT.format(chunk=chunk)
        response = self._llm_service.complete(prompt)

        try:
            response = response.replace('```json', '')
            response = response.replace('```', '')
            return json.loads(response)
        except json.JSONDecodeError:
            print('Ao extrair as referências do Chunk atual o modelo não respondeu em JSON.')
            return []

    def extract_from_markdown(self, file_path: Union[str, Path]) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        final_file_json = {
            'answer': file_path,
            'references': []
        }
        chunks = self._split_into_chunks(content)
        all_references = []
        global_id = 1
        output_file: Path = Path("")

        for i, chunk in enumerate(chunks):
            print(f"Processando chunk {i + 1}/{len(chunks)}...")
            references = self._extract_references(chunk)

            for ref in references:
                ref["id"] = global_id
                global_id += 1
                all_references.append(ref)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self._output_dir / f"references_lmStudio_{timestamp}.json"
        final_file_json["references"] = all_references

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_file_json, f, ensure_ascii=False, indent=2)

        print(f"Referências salvas em: {output_file}")

        return str(output_file)