#!/usr/bin/env python
import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

from src.services.file_converter import FileConverter
from src.services.llm_service import LLMService
from src.services.reference_extractor import ReferenceExtractor

load_dotenv()

llm_base_url = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1/")
llm_model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

DOCUMENTS_DIR = Path("./documents")
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

REGISTER_FILE = Path(os.getenv("REGISTER_FILE", "./register/register.json"))

def load_register() -> list:
    if REGISTER_FILE.exists():
        with open(REGISTER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_register(register: list):
    with open(REGISTER_FILE, "w", encoding="utf-8") as f:
        json.dump(register, f, ensure_ascii=False, indent=2)

def download_references(answer_path: Path, existing_entry: dict = None) -> dict:
    llm = LLMService(
        api_key="",
        model=llm_model,
        provider="openai",
        base_url=llm_base_url
    )

    extractor = ReferenceExtractor(llm_service=llm)
    converter = FileConverter()

    print(f"\nProcessando: {answer_path}")

    result_path = extractor.extract_from_markdown(str(answer_path))
    with open(result_path, "r", encoding="utf-8") as f:
        result_json = json.load(f)

    references = result_json.get("references", [])

    already_downloaded = set()
    already_errored_urls = set()
    existing_documents = []
    if existing_entry:
        existing_documents = existing_entry.get("documents", [])
        already_downloaded = {Path(d).name for d in existing_documents}
        already_errored_urls = {e["url"] for e in existing_entry.get("errors", [])}

    documents = list(existing_documents)
    errors = []
    skipped = 0

    for ref in references:
        url = ref.get("url")
        if not url:
            continue

        doc_id = ref.get("id", 0)
        safe_name = answer_path.stem.replace(" ", "_")
        output_path = DOCUMENTS_DIR / f"{safe_name}_doc_{doc_id}.md"

        if output_path.name in already_downloaded:
            skipped += 1
            continue

        if url in already_errored_urls:
            skipped += 1
            continue

        print(f"  Baixando: {url}")
        try:
            converter.convert(url=url, output_path=output_path)
            documents.append(str(output_path))
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"    ERRO: {error_type} - {error_msg}")
            errors.append({
                "url": url,
                "error_type": error_type,
                "error_message": error_msg,
                "reference_id": doc_id
            })

    if skipped:
        print(f"  {skipped} referências já processadas, ignoradas")

    return {
        "answer": str(answer_path),
        "documents": documents,
        "errors": errors
    }

def download_errors_only(answer_path: Path, existing_entry: dict) -> dict:
    converter = FileConverter()

    failed_urls = {e["url"]: e for e in existing_entry.get("errors", [])}
    if not failed_urls:
        print(f"  Nenhum erro anterior para reprocessar: {answer_path}")
        return existing_entry

    print(f"\nReprocessando {len(failed_urls)} erros anteriores: {answer_path}")

    documents = list(existing_entry.get("documents", []))
    new_errors = []

    for url, error_info in failed_urls.items():
        doc_id = error_info.get("reference_id", 0)
        safe_name = Path(answer_path).stem.replace(" ", "_")
        output_path = DOCUMENTS_DIR / f"{safe_name}_doc_{doc_id}.md"

        print(f"  Retry: {url}")
        try:
            converter.convert(url=url, output_path=output_path)
            documents.append(str(output_path))
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"    ERRO: {error_type} - {error_msg}")
            new_errors.append({
                "url": url,
                "error_type": error_type,
                "error_message": error_msg,
                "reference_id": doc_id
            })

    recovered = len(failed_urls) - len(new_errors)
    if recovered:
        print(f"  {recovered} de {len(failed_urls)} erros recuperados")

    return {
        "answer": str(answer_path),
        "documents": documents,
        "errors": new_errors
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Download e conversão de referências")
    parser.add_argument(
        "answer_files", nargs="*",
        help="Caminhos dos arquivos de resposta para processar"
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help="Apenas reprocessar URLs que falharam anteriormente"
    )
    parser.add_argument(
        "--register", type=str, default=None,
        help="Caminho do arquivo de registro (padrão: ./register/register.json)"
    )
    args = parser.parse_args()

    global REGISTER_FILE
    if args.register:
        REGISTER_FILE = Path(args.register)

    answer_files = args.answer_files
    if not answer_files:
        print("Nenhum arquivo de resposta informado.")
        print("Uso: python main.py <arquivo1.md> [arquivo2.md ...]")
        print("     python main.py --retry-errors <arquivo1.md>")
        sys.exit(1)

    register = load_register()
    register_map = {entry["answer"]: entry for entry in register}
    skipped_answers = []

    for answer_path in answer_files:
        existing_entry = register_map.get(str(answer_path))

        if args.retry_errors:
            if not existing_entry:
                print(f">>> Sem registro anterior, ignorando: {answer_path}")
                continue
            entry = download_errors_only(Path(answer_path), existing_entry)
        else:
            print(f">>> Fazendo download das referências: {answer_path}")
            entry = download_references(Path(answer_path), existing_entry)

        if entry["documents"]:
            if existing_entry:
                register.remove(existing_entry)
            register.append(entry)
            register_map[str(answer_path)] = entry
            save_register(register)
            print(f"  {len(entry['documents'])} documentos, {len(entry['errors'])} erros")
        else:
            print(f"  ERRO: Nenhum documento baixado")
            skipped_answers.append(str(answer_path))
            continue

    if skipped_answers:
        print(f"\n{len(skipped_answers)} respostas ignoradas (sem documentos)")


if __name__ == "__main__":
    main()
