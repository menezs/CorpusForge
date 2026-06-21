#!/usr/bin/env python
import concurrent.futures
import json
import logging
import os
import sys
import threading
import argparse
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from src.logging_config import setup_logging, tqdm_logging
from src.services.file_converter import FileConverter
from src.services.llm_service import LLMService
from src.services.reference_extractor import ReferenceExtractor

logger = logging.getLogger(__name__)

load_dotenv()
setup_logging()

llm_base_url = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1/")
llm_model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

DOCUMENTS_DIR = Path("./documents")
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

REGISTER_FILE = Path(os.getenv("REGISTER_FILE", "./register/register.json"))
register_lock = threading.Lock()


def load_register() -> list:
    if REGISTER_FILE.exists():
        with open(REGISTER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_register(register: list):
    tmp_path = REGISTER_FILE.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(register, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, REGISTER_FILE)


def create_llm_service() -> LLMService:
    return LLMService(
        api_key="",
        model=llm_model,
        provider="openai",
        base_url=llm_base_url,
    )


def download_references(
    answer_path: Path,
    llm: LLMService,
    existing_entry: dict = None,
    max_workers: int = 4,
) -> dict:
    extractor = ReferenceExtractor(llm_service=llm)
    converter = FileConverter()

    logger.info("Processando: %s", answer_path)

    result_path = extractor.extract_references(str(answer_path))
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

    safe_name = answer_path.stem.replace(" ", "_")

    def download_one(ref):
        url = ref.get("url")
        doc_id = ref.get("id", 0)
        output_path = DOCUMENTS_DIR / f"{safe_name}_doc_{doc_id}.md"
        try:
            logger.info("Baixando: %s", url)
            converter.convert(url=url, output_path=output_path)
            return ("ok", str(output_path))
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error("ERRO: %s - %s", error_type, error_msg)
            return ("error", {
                "url": url,
                "error_type": error_type,
                "error_message": error_msg,
                "reference_id": doc_id,
            })

    refs_to_download = []
    skipped = 0

    for ref in references:
        url = ref.get("url")
        if not url:
            continue

        doc_id = ref.get("id", 0)
        output_path = DOCUMENTS_DIR / f"{safe_name}_doc_{doc_id}.md"

        if output_path.name in already_downloaded:
            skipped += 1
            continue

        if url in already_errored_urls:
            skipped += 1
            continue

        refs_to_download.append(ref)

    documents = list(existing_documents)
    errors = []

    with tqdm_logging():
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_one, ref): ref for ref in refs_to_download}
            with tqdm(total=len(futures), desc="Baixando referências", unit="ref") as pbar:
                for future in concurrent.futures.as_completed(futures):
                    status, result = future.result()
                    if status == "ok":
                        documents.append(result)
                    else:
                        errors.append(result)
                    pbar.update(1)

    if skipped:
        logger.info("%d referências já processadas, ignoradas", skipped)

    return {
        "answer": str(answer_path),
        "documents": documents,
        "errors": errors,
    }


def download_errors_only(answer_path: Path, existing_entry: dict, max_workers: int = 4) -> dict:
    converter = FileConverter()

    failed_urls = {e["url"]: e for e in existing_entry.get("errors", [])}
    if not failed_urls:
        logger.info("Nenhum erro anterior para reprocessar: %s", answer_path)
        return existing_entry

    logger.info("Reprocessando %d erros anteriores: %s", len(failed_urls), answer_path)

    retryable_keywords = ["429", "Timeout", "ConnectionError", "403", "Forbidden", "rate limit"]
    safe_name = Path(answer_path).stem.replace(" ", "_")

    def retry_one(url, error_info):
        doc_id = error_info.get("reference_id", 0)
        error_msg = error_info.get("error_message", "")

        is_retryable = any(keyword.lower() in error_msg.lower() for keyword in retryable_keywords)
        if not is_retryable:
            return ("skip", error_info)

        output_path = DOCUMENTS_DIR / f"{safe_name}_doc_{doc_id}.md"

        logger.info("Retry: %s", url)
        try:
            converter.convert(url=url, output_path=output_path)
            return ("ok", str(output_path))
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error("ERRO: %s - %s", error_type, error_msg)
            return ("error", {
                "url": url,
                "error_type": error_type,
                "error_message": error_msg,
                "reference_id": doc_id,
            })

    documents = list(existing_entry.get("documents", []))
    new_errors = []
    skipped_errors = []

    with tqdm_logging():
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(retry_one, url, error_info): url
                for url, error_info in failed_urls.items()
            }
            with tqdm(total=len(futures), desc="Reprocessando erros", unit="ref") as pbar:
                for future in concurrent.futures.as_completed(futures):
                    status, result = future.result()
                    if status == "ok":
                        documents.append(result)
                    elif status == "skip":
                        skipped_errors.append(result)
                    else:
                        new_errors.append(result)
                    pbar.update(1)

    recovered = len(failed_urls) - len(new_errors) - len(skipped_errors)
    if recovered:
        logger.info("%d de %d erros recuperados", recovered, len(failed_urls))
    if skipped_errors:
        logger.info("%d erros permanentes ignorados", len(skipped_errors))

    return {
        "answer": str(answer_path),
        "documents": documents,
        "errors": new_errors + skipped_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download e conversão de referências")
    parser.add_argument(
        "answer_files", nargs="*",
        help="Arquivos de resposta para processar (md, pdf, docx)",
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help="Apenas reprocessar URLs que falharam anteriormente",
    )
    parser.add_argument(
        "--register", type=str, default=None,
        help="Caminho do arquivo de registro (padrão: ./register/register.json)",
    )
    parser.add_argument(
        "--max-workers", type=int, default=4,
        help="Número máximo de downloads paralelos (padrão: 4)",
    )
    args = parser.parse_args()

    global REGISTER_FILE
    if args.register:
        REGISTER_FILE = Path(args.register)

    answer_files = args.answer_files
    if not answer_files:
        logger.error("Nenhum arquivo de resposta informado.")
        logger.info("Uso: python main.py <arquivo.md|pdf|docx> [arquivo2.md ...]")
        logger.info("     python main.py --retry-errors <arquivo.md>")
        sys.exit(1)

    llm = create_llm_service()
    register = load_register()
    register_map = {entry["answer"]: entry for entry in register}
    skipped_answers = []

    for answer_path in answer_files:
        existing_entry = register_map.get(str(answer_path))

        if args.retry_errors:
            if not existing_entry:
                logger.warning("Sem registro anterior, ignorando: %s", answer_path)
                continue
            entry = download_errors_only(
                Path(answer_path), existing_entry, max_workers=args.max_workers,
            )
        else:
            logger.info("Fazendo download das referências: %s", answer_path)
            entry = download_references(
                Path(answer_path), llm, existing_entry, max_workers=args.max_workers,
            )

        if entry["documents"]:
            with register_lock:
                if existing_entry:
                    register.remove(existing_entry)
                register.append(entry)
                register_map[str(answer_path)] = entry
                save_register(register)
            logger.info("%d documentos, %d erros", len(entry["documents"]), len(entry["errors"]))
        else:
            logger.warning("Nenhum documento baixado")
            skipped_answers.append(str(answer_path))
            continue

    if skipped_answers:
        logger.warning("%d respostas ignoradas (sem documentos)", len(skipped_answers))


if __name__ == "__main__":
    main()
