import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Union
from tqdm import tqdm
from ..logging_config import tqdm_logging
from .llm_service import LLMService

import pymupdf4llm
import docx

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _enc = None

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".pdf", ".docx"}


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
7. URLs no texto podem aparecer com espaços ou quebras de linha (extração de PDF).
   Nesses casos:
   - Mantenha o texto EXATAMENTE como aparece no parágrafo
   - NÃO substitua espaços por %20
   - NÃO remova espaços
   - NÃO remova hífens (-)
   - O tratamento de espaços em URLs será feito em etapa posterior

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
        if _enc is not None:
            return len(_enc.encode(text))
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

    @staticmethod
    def _normalize_ref_key(url: str) -> str:
        """Normaliza URL para dedup (DOI → URL canônica, case-insensitive)."""
        url = url.strip().rstrip("/")
        if "doi.org" in url:
            doi = url.split("doi.org/", 1)[-1]
            return f"doi:{doi.lower()}"
        if url.startswith("10."):
            return f"doi:{url.lower()}"
        return url.lower()

    def _extract_references(self, chunk: str) -> List[Dict[str, Any]]:
        prompt = self.DEFAULT_PROMPT.format(chunk=chunk)
        response = self._llm_service.complete(prompt)

        try:
            response = response.replace('```json', '')
            response = response.replace('```', '')
            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning("Ao extrair as referências do Chunk atual o modelo não respondeu em JSON.")
            return []

    def _read_content(self, path: Path) -> str:
        """Extrai texto de um arquivo conforme sua extensão."""
        suffix = path.suffix.lower()

        if suffix in (".md", ".markdown"):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

        if suffix == ".pdf":
            markdown = pymupdf4llm.to_markdown(str(path))
            if markdown is None:
                raise ValueError(f"Não foi possível converter o PDF: {path}")
            return markdown

        if suffix == ".docx":
            doc = docx.Document(str(path))
            return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())

        raise ValueError(f"Formato não suportado: {suffix}")

    def extract_references(self, file_path: Union[str, Path]) -> str:
        """Extrai referências de um arquivo (md, pdf, docx)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Formato não suportado: {suffix}. Use: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

        logger.info("Lendo conteúdo de: %s", path.name)
        content = self._read_content(path)

        if not content or not content.strip():
            raise ValueError(f"Arquivo vazio ou sem conteúdo extraível: {path}")

        final_file_json = {
            'answer': str(file_path),
            'references': []
        }
        chunks = self._split_into_chunks(content)
        all_references = []
        seen_keys: set = set()
        global_id = 1
        output_file: Path = Path("")

        with tqdm_logging():
            for i, chunk in enumerate(tqdm(chunks, desc="Extraindo referências", unit="chunk")):
                logger.info("Processando chunk %d/%d...", i + 1, len(chunks))
                references = self._extract_references(chunk)

                for ref in references:
                    url = ref.get("url", "").strip()
                    if not url:
                        continue
                    key = self._normalize_ref_key(url)
                    if key in seen_keys:
                        logger.debug("Referência duplicada ignorada: %s", url)
                        continue
                    seen_keys.add(key)
                    ref["id"] = global_id
                    global_id += 1
                    all_references.append(ref)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self._output_dir / f"references_lmStudio_{timestamp}.json"
        final_file_json["references"] = all_references

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_file_json, f, ensure_ascii=False, indent=2)

        logger.info("Referências salvas em: %s", output_file)

        return str(output_file)

    def extract_from_markdown(self, file_path: Union[str, Path]) -> str:
        """Alias para extract_references (compatibilidade retroativa)."""
        return self.extract_references(file_path)
