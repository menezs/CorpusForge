import logging
import time
import tempfile
from urllib.parse import urlparse

import trafilatura
import requests
import cloudscraper
from pathlib import Path
from typing import Optional, Union, Tuple

import pymupdf4llm

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def validate_url(url: str) -> bool:
    """Retorna True se a URL é válida para download (http/https com netloc)."""
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False
    if not parsed.netloc:
        return False
    return True


class FileConverter:
    def _fetch_html(self, url: str, retries: int = 2, backoff: float = 2.0) -> Tuple[str, str]:
        """Retorna (conteudo, content_type)."""
        last_exc = None
        for attempt in range(retries + 1):
            try:
                r = requests.get(
                    url,
                    headers=_BROWSER_HEADERS,
                    timeout=30,
                    allow_redirects=True,
                )
                content_type = r.headers.get("content-type", "")
                if r.status_code == 404:
                    raise ValueError(f"Página não encontrada (404): {url}")
                if r.status_code == 403:
                    logger.warning("403 com requests, tentando cloudscraper...")
                    scraper = cloudscraper.create_scraper()
                    r = scraper.get(url, timeout=30)
                    content_type = r.headers.get("content-type", "")
                    if r.status_code == 404:
                        raise ValueError(f"Página não encontrada (404): {url}")
                    if r.status_code == 403:
                        logger.warning("403 com cloudscraper, tentando Playwright...")
                        playwright_content = self._playwright_extract(url)
                        if playwright_content is not None:
                            return playwright_content, "text/html"
                        raise ValueError(f"Acesso negado (403) por todas as tentativas: {url}")
                    r.raise_for_status()
                elif r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 60))
                    logger.warning("Rate limit (429), aguardando %ds...", retry_after)
                    time.sleep(retry_after)
                    continue
                else:
                    r.raise_for_status()

                if "application/pdf" in content_type:
                    return r.content.decode("latin-1"), "application/pdf"

                html = r.text
                if not html or len(html) < 50:
                    raise ValueError(f"Resposta vazia ou muito pequena de: {url}")
                return html, content_type

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError) as e:
                last_exc = e
                if attempt < retries:
                    wait = backoff * (2 ** attempt)
                    logger.warning("Tentativa %d falhou, retry em %.1fs: %s", attempt + 1, wait, e)
                    time.sleep(wait)
            except (requests.exceptions.MissingSchema,
                    requests.exceptions.InvalidURL,
                    requests.exceptions.InvalidSchema) as e:
                raise ValueError(f"URL inválida: {url} - {e}")

        raise ValueError(f"Não foi possível acessar a URL após {retries + 1} tentativas: {url} - {last_exc}")

    def _playwright_extract(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        logger.info("Fallback Playwright: %s", url)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(_BROWSER_HEADERS)
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                browser.close()
            markdown = trafilatura.extract(html, output_format="markdown")
            return markdown
        except Exception as e:
            logger.error("Playwright falhou: %s: %s", type(e).__name__, e)
            return None

    def convert(
        self,
        input_path: Optional[Union[str, Path]] = None,
        output_path: Optional[Union[str, Path]] = None,
        url: Optional[str] = None,
    ) -> str:
        if url is not None:
            if not validate_url(url):
                raise ValueError(f"URL inválida ou não suportada: {url}")
            return self._from_url(url, output_path)

        if input_path is None:
            raise ValueError("Forneça input_path ou url")

        return self._from_file(input_path, output_path)

    def _from_file(self, input_path: Union[str, Path], output_path: Optional[Union[str, Path]] = None) -> str:
        input_file = Path(input_path)

        if not input_file.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {input_file}")

        if output_path is None:
            output_file = input_file.with_suffix(".md")
        else:
            output_file = Path(output_path)

        markdown = pymupdf4llm.to_markdown(str(input_file))
        if markdown is None:
            raise ValueError(f"Não foi possível converter o arquivo: {input_file}")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown)

        return str(output_file)

    def _from_url(self, url: str, output_path: Optional[Union[str, Path]] = None) -> str:
        if output_path is None:
            raise ValueError("output_path é obrigatório quando usando url")

        output_file = Path(output_path)

        if url.endswith(".pdf"):
            file_name = url.split('/')[-1].replace('.pdf', '')
            if not file_name:
                file_name = "downloaded"
            path_to_download = output_file.parent / f'{file_name}.pdf'
            self._download_pdf(url=url, output_path=path_to_download)
            self._from_file(path_to_download, output_file)
            return str(output_file)

        content, content_type = self._fetch_html(url)

        if "application/pdf" in content_type:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content.encode("latin-1"))
                tmp_path = tmp.name
            self._from_file(tmp_path, output_file)
            Path(tmp_path).unlink()
            return str(output_file)

        markdown = trafilatura.extract(content, output_format="markdown")

        if markdown is None:
            markdown = self._playwright_extract(url)

        if markdown is None:
            raise ValueError(f"Não foi possível extrair conteúdo de: {url}")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown)

        return str(output_file)

    def _download_pdf(self, url: str, output_path: Union[str, Path]):
        r = requests.get(url, headers=_BROWSER_HEADERS, stream=True, timeout=30)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
