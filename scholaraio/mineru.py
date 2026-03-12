"""
pdf_to_markdown.py �?使用本地 MinerU 服务�?PDF 转换�?Markdown
================================================================

调用本地部署�?MinerU API (默认 http://localhost:8000) �?PDF 文件转换�?
Markdown 格式。支持单文件转换和批量处理整个目录�?

前置条件
--------
    需要先启动 MinerU API 服务，默认监�?http://localhost:8000�?
    可用 ``python3 pdf_to_markdown.py status`` 检查服务是否在线�?

工作流程
--------
1. 扫描 PDF 文件 (单个或目录批�?
2. 检查是否已有同�?.md 输出 �?有则跳过 (--force 可强制重新转�?
3. 调用 MinerU POST /file_parse 接口上传 PDF 并获�?Markdown
4. �?Markdown 写入指定目录 (默认�?PDF 同目�?, 文件�?= PDF�?md
5. 可选同时保�?content_list JSON (--save-content-list)

输出文件
--------
    <pdf_stem>.md               主输�? MinerU 转换后的 Markdown
    <pdf_stem>_content_list.json  (可�? MinerU 结构化内容列�?

    输出位置: 默认�?PDF 同目�? 可通过 -o/--output-dir 指定统一输出目录�?

命令行用�?
----------
    # 检�?MinerU 服务状�?
    python3 pdf_to_markdown.py status
    python3 pdf_to_markdown.py status --api-url http://host:port

    # 单文件转�?
    python3 pdf_to_markdown.py convert paper.pdf
    python3 pdf_to_markdown.py convert paper.pdf -o ./output/       # 指定输出目录
    python3 pdf_to_markdown.py convert paper.pdf --start-page 0 --end-page 10
    python3 pdf_to_markdown.py convert paper.pdf --backend vlm-auto-engine
    python3 pdf_to_markdown.py convert paper.pdf --lang en          # 英文 PDF
    python3 pdf_to_markdown.py convert paper.pdf --parse-method ocr # 强制 OCR
    python3 pdf_to_markdown.py convert paper.pdf --no-formula --no-table
    python3 pdf_to_markdown.py convert paper.pdf --save-content-list
    python3 pdf_to_markdown.py convert paper.pdf --dry-run          # 预览, 不写文件

    # 批量处理
    python3 pdf_to_markdown.py batch ./papers/                      # 目录下所�?PDF
    python3 pdf_to_markdown.py batch ./papers/ -r                   # 递归子目�?
    python3 pdf_to_markdown.py batch ./papers/ -o ./md_output/      # 指定输出目录
    python3 pdf_to_markdown.py batch ./papers/ --force              # 重新转换已有 .md �?
    python3 pdf_to_markdown.py batch ./papers/ --dry-run            # 干跑预览
    python3 pdf_to_markdown.py batch ./papers/ --backend pipeline --lang ch

公共选项 (convert / batch 共用)
-------------------------------
    -o, --output-dir DIR    输出目录 (默认: �?PDF 同目�?
    --api-url URL           MinerU 服务地址 (默认: http://localhost:8000)
    --backend BACKEND       解析后端 (见下�? 默认: pipeline)
    --lang LANG             OCR 语言: ch(中英), en, latin �?(默认: ch)
    --parse-method METHOD   PDF 解析方式: auto / txt / ocr (默认: auto)
    --no-formula            禁用公式解析
    --no-table              禁用表格解析
    --save-content-list     同时保存 content_list JSON
    --dry-run               预览操作, 不实际写文件

MinerU 后端选项 (--backend)
---------------------------
    pipeline            通用, 支持多语言, 无幻�?(默认, 推荐)
    vlm-auto-engine     本地算力高精�? 仅中英文
    vlm-http-client     远程算力高精�?(OpenAI 兼容), 仅中英文
    hybrid-auto-engine  新一代本地高精度, 支持多语言
    hybrid-http-client  远程+少量本地算力, 支持多语言

依赖
----
    Python 3.10+, requests
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import logging

import requests

_log = logging.getLogger(__name__)

# ============================================================================
#  Constants
# ============================================================================

DEFAULT_API_URL = "http://localhost:8000"
PARSE_ENDPOINT = "/file_parse"

VALID_BACKENDS = [
    "pipeline",
    "vlm-auto-engine",
    "vlm-http-client",
    "hybrid-auto-engine",
    "hybrid-http-client",
]

DEFAULT_BACKEND = "pipeline"
DEFAULT_LANG = "ch"
API_TIMEOUT = 600  # PDF parsing can take a long time


# ============================================================================
#  Data Structures
# ============================================================================


@dataclass
class ConvertResult:
    """单次 PDF �?Markdown 转换的结果�?

    Attributes:
        pdf_path: 原始 PDF 文件路径�?
        md_path: 输出�?Markdown 文件路径，转换失败时�?``None``�?
        success: 转换是否成功�?
        pages_parsed: 解析的页数�?
        elapsed_seconds: 转换耗时（秒）�?
        error: 失败时的错误信息，成功时�?``None``�?
        md_size: 输出 Markdown 的字节数�?
    """

    pdf_path: Path
    md_path: Path | None = None
    success: bool = False
    pages_parsed: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    md_size: int = 0  # bytes


@dataclass
class ConvertOptions:
    """PDF 转换选项�?

    Attributes:
        api_url: MinerU 服务地址�?
        output_dir: 输出目录，为 ``None`` 时与 PDF 同目录�?
        backend: MinerU 解析后端（``pipeline`` | ``vlm-auto-engine`` 等）�?
        lang: OCR 语言（``ch`` | ``en`` | ``latin`` 等）�?
        parse_method: 解析方式（``auto`` | ``txt`` | ``ocr``）�?
        formula_enable: 是否启用公式解析�?
        table_enable: 是否启用表格解析�?
        start_page: 起始页（0-indexed）�?
        end_page: 结束页（0-indexed）�?
        save_content_list: 是否同时保存 content_list JSON�?
        force: 是否强制重新转换已有 ``.md`` 的文件�?
        dry_run: 预览模式，不写文件�?
    """

    api_url: str = DEFAULT_API_URL
    output_dir: Path | None = None
    backend: str = DEFAULT_BACKEND
    lang: str = DEFAULT_LANG
    parse_method: str = "auto"
    formula_enable: bool = True
    table_enable: bool = True
    start_page: int = 0
    end_page: int = 99999
    save_content_list: bool = False
    force: bool = False
    dry_run: bool = False


# ============================================================================
#  MinerU API
# ============================================================================


def check_server(api_url: str = DEFAULT_API_URL) -> bool:
    """检�?MinerU 服务是否可达�?

    Args:
        api_url: MinerU 服务地址，默�?``http://localhost:8000``�?

    Returns:
        可达返回 ``True``，不可达返回 ``False``�?
    """
    try:
        resp = requests.get(f"{api_url}/docs", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def convert_pdf(pdf_path: Path, opts: ConvertOptions) -> ConvertResult:
    """通过 MinerU API 将单�?PDF 转换�?Markdown�?

    �?PDF 上传到本�?MinerU 服务，接�?Markdown 内容并写入磁盘�?

    Args:
        pdf_path: PDF 文件路径�?
        opts: 转换选项（API 地址、后端、输出目录等）�?

    Returns:
        :class:`ConvertResult` 实例，包含转换结果和状态�?
    """
    result = ConvertResult(pdf_path=pdf_path)
    t0 = time.time()

    # Determine output path
    if opts.output_dir:
        out_dir = opts.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = pdf_path.parent

    md_path = out_dir / (pdf_path.stem + ".md")
    result.md_path = md_path

    # Dry run: just report what would happen
    if opts.dry_run:
        exists_tag = " (exists, would overwrite)" if md_path.exists() else ""
        _log.debug("dry-run: %s%s", md_path.name, exists_tag)
        result.success = True
        return result

    # Skip if already exists (unless --force)
    if md_path.exists() and not opts.force:
        _log.debug("skip (already exists): %s", md_path.name)
        result.success = True
        result.md_path = md_path
        return result

    # Build multipart form data
    url = f"{opts.api_url}{PARSE_ENDPOINT}"

    form_data = {
        "backend": (None, opts.backend),
        "parse_method": (None, opts.parse_method),
        "formula_enable": (None, str(opts.formula_enable).lower()),
        "table_enable": (None, str(opts.table_enable).lower()),
        "return_md": (None, "true"),
        "return_middle_json": (None, "false"),
        "return_content_list": (None, str(opts.save_content_list).lower()),
        "return_model_output": (None, "false"),
        "return_images": (None, "false"),
        "start_page_id": (None, str(opts.start_page)),
        "end_page_id": (None, str(opts.end_page)),
    }

    # lang_list needs to be sent as repeated form fields
    # requests handles this via the files parameter
    try:
        with open(pdf_path, "rb") as f:
            files = {
                "files": (pdf_path.name, f, "application/pdf"),
            }
            # Add lang_list as a form field
            form_data["lang_list"] = (None, opts.lang)

            resp = requests.post(url, files={**files, **form_data}, timeout=API_TIMEOUT)

    except requests.ConnectionError:
        result.error = f"Cannot connect to MinerU server at {opts.api_url}"
        result.elapsed_seconds = time.time() - t0
        return result
    except requests.Timeout:
        result.error = f"Request timed out after {API_TIMEOUT}s"
        result.elapsed_seconds = time.time() - t0
        return result

    result.elapsed_seconds = time.time() - t0

    if resp.status_code != 200:
        result.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        return result

    # Parse response
    try:
        data = resp.json()
    except ValueError:
        result.error = "Invalid JSON response from server"
        return result

    # Extract markdown content from response
    # MinerU API returns a list (one entry per uploaded file)
    md_content = _extract_markdown(data)
    if md_content is None:
        result.error = f"No markdown content in response. Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        return result

    # Write markdown
    md_path.write_text(md_content, encoding="utf-8")
    result.success = True
    result.md_size = len(md_content.encode("utf-8"))

    # Optionally save content_list JSON
    if opts.save_content_list:
        cl = _extract_field(data, "content_list")
        if cl:
            cl_path = out_dir / (pdf_path.stem + "_content_list.json")
            cl_path.write_text(
                json.dumps(cl, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    _log.info(
        "-> %s (%s, %.1fs)",
        md_path.name,
        _fmt_size(result.md_size),
        result.elapsed_seconds,
    )
    return result


def _extract_markdown(data) -> str | None:
    """Extract markdown text from MinerU API response.

    Actual response format (MinerU �?.7):
        {
          "backend": "pipeline",
          "version": "2.7.6",
          "results": {
            "<filename_stem>": {
              "md_content": "..."
            }
          }
        }
    """
    if not isinstance(data, dict):
        return None

    # Primary path: results �?{filename} �?md_content
    results = data.get("results")
    if isinstance(results, dict):
        for _filename, entry in results.items():
            if isinstance(entry, dict):
                md = entry.get("md_content")
                if isinstance(md, str) and md.strip():
                    return md

    # Fallback: direct md_content at top level
    for key in ("md_content", "md", "markdown", "content"):
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key]

    return None


def _extract_field(data, field_name):
    """Extract a named field from MinerU API response.

    Navigates: data["results"][first_key][field_name]
    """
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if isinstance(results, dict):
        for _filename, entry in results.items():
            if isinstance(entry, dict) and field_name in entry:
                return entry[field_name]
    return data.get(field_name)


# ============================================================================
#  Cloud API
# ============================================================================

CLOUD_API_URL = "https://mineru.net/api/v4"
CLOUD_POLL_INTERVAL = 5  # seconds between status checks
CLOUD_TIMEOUT = 600  # max wait time for cloud parsing


def convert_pdf_cloud(
    pdf_path: Path,
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str = CLOUD_API_URL,
) -> ConvertResult:
    """通过 MinerU �?API 将单�?PDF 转换�?Markdown�?

    工作流程: 获取签名上传 URL �?PUT 上传 PDF �?轮询解析结果 �?下载 Markdown�?
    本地 MinerU 不可达时作为 :func:`convert_pdf` �?fallback 使用�?

    Args:
        pdf_path: PDF 文件路径�?
        opts: 转换选项（输出目录、后端、语言等，复用本地 API 的选项结构）�?
        api_key: MinerU �?API 密钥（Bearer token）�?
        cloud_url: MinerU �?API 基础 URL，默�?``https://mineru.net/api/v4``�?

    Returns:
        :class:`ConvertResult` 实例，包含转换结果和状态�?
    """
    result = ConvertResult(pdf_path=pdf_path)
    t0 = time.time()

    out_dir = opts.output_dir if opts.output_dir else pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (pdf_path.stem + ".md")
    result.md_path = md_path

    if opts.dry_run:
        exists_tag = " (exists, would overwrite)" if md_path.exists() else ""
        _log.debug("dry-run [cloud]: %s%s", md_path.name, exists_tag)
        result.success = True
        return result

    if md_path.exists() and not opts.force:
        _log.debug("skip (already exists): %s", md_path.name)
        result.success = True
        return result

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Step 1: request signed upload URL
    data_id = pdf_path.stem
    payload: dict = {
        "files": [{"name": pdf_path.name, "data_id": data_id}],
        "model_version": opts.backend,
        "enable_formula": opts.formula_enable,
        "enable_table": opts.table_enable,
        "language": opts.lang,
    }
    if opts.parse_method == "ocr":
        payload["is_ocr"] = True

    try:
        resp = requests.post(
            f"{cloud_url}/file-urls/batch",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        result.error = f"�?API 请求失败: {e}"
        result.elapsed_seconds = time.time() - t0
        return result

    if resp.status_code != 200:
        result.error = f"�?API HTTP {resp.status_code}: {resp.text[:200]}"
        result.elapsed_seconds = time.time() - t0
        return result

    try:
        resp_data = resp.json()
    except ValueError:
        result.error = "�?API 返回�?JSON 响应"
        result.elapsed_seconds = time.time() - t0
        return result
    if resp_data.get("code") != 0:
        result.error = f"�?API 错误: {resp_data.get('msg', resp.text[:200])}"
        result.elapsed_seconds = time.time() - t0
        return result

    batch_data = resp_data.get("data", {})
    batch_id = batch_data.get("batch_id", "")
    file_urls = batch_data.get("file_urls", [])
    if not file_urls:
        result.error = "�?API 未返回上�?URL"
        result.elapsed_seconds = time.time() - t0
        return result

    # file_urls is a list of URL strings
    upload_url = (
        file_urls[0] if isinstance(file_urls[0], str) else file_urls[0].get("url", "")
    )
    if not upload_url:
        result.error = "�?API 返回的上�?URL 为空"
        result.elapsed_seconds = time.time() - t0
        return result

    # Step 2: upload PDF via PUT
    try:
        with open(pdf_path, "rb") as f:
            put_resp = requests.put(
                upload_url,
                data=f,
                timeout=120,
            )
        if put_resp.status_code not in (200, 201):
            result.error = f"PDF 上传失败: HTTP {put_resp.status_code}"
            result.elapsed_seconds = time.time() - t0
            return result
    except requests.RequestException as e:
        result.error = f"PDF 上传失败: {e}"
        result.elapsed_seconds = time.time() - t0
        return result

    _log.debug("PDF uploaded, cloud parsing (batch_id: %s...)", batch_id[:12])

    # Step 3: poll for results
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + CLOUD_TIMEOUT

    while time.time() < deadline:
        time.sleep(CLOUD_POLL_INTERVAL)
        try:
            poll_resp = requests.get(
                f"{cloud_url}/extract-results/batch/{batch_id}",
                headers=poll_headers,
                timeout=30,
            )
        except requests.RequestException:
            continue

        if poll_resp.status_code != 200:
            continue

        try:
            poll_data = poll_resp.json()
        except ValueError:
            continue
        if poll_data.get("code") != 0:
            continue

        extract_results = poll_data.get("data", {}).get("extract_result", [])
        if not extract_results:
            continue

        item = extract_results[0]
        state = item.get("state", "")

        if state == "failed":
            result.error = f"云端解析失败: {item.get('err_msg', 'unknown')}"
            result.elapsed_seconds = time.time() - t0
            return result

        if state == "done":
            md_content = _download_cloud_result(item, out_dir)
            if md_content is None:
                result.error = (
                    f"无法从云端结果提�?Markdown。响应键: {list(item.keys())}"
                )
                result.elapsed_seconds = time.time() - t0
                return result

            md_path.write_text(md_content, encoding="utf-8")
            result.success = True
            result.md_size = len(md_content.encode("utf-8"))
            result.elapsed_seconds = time.time() - t0
            _log.info(
                "-> [cloud] %s (%s, %.1fs)",
                md_path.name,
                _fmt_size(result.md_size),
                result.elapsed_seconds,
            )
            return result

        if state == "running":
            extracted = item.get("extracted_pages", "?")
            total = item.get("total_pages", "?")
            _log.debug("cloud parsing... %s/%s pages", extracted, total)

    result.error = f"云端解析超时（{CLOUD_TIMEOUT}s�?
    result.elapsed_seconds = time.time() - t0
    return result


CLOUD_BATCH_SIZE = 20  # max files per batch request


def convert_pdfs_cloud_batch(
    pdf_paths: list[Path],
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str = CLOUD_API_URL,
) -> list[ConvertResult]:
    """通过 MinerU �?API 批量转换 PDF �?Markdown�?

    所�?PDF 在一�?batch 内提交，并行上传，统一轮询�?
    超过 ``CLOUD_BATCH_SIZE`` 时自动分批�?

    Args:
        pdf_paths: PDF 文件路径列表�?
        opts: 转换选项�?
        api_key: MinerU �?API 密钥�?
        cloud_url: MinerU �?API 基础 URL�?

    Returns:
        �?``pdf_paths`` 等长�?:class:`ConvertResult` 列表�?
    """
    if not pdf_paths:
        return []

    # Split into chunks
    all_results: list[ConvertResult] = []
    for chunk_start in range(0, len(pdf_paths), CLOUD_BATCH_SIZE):
        chunk = pdf_paths[chunk_start : chunk_start + CLOUD_BATCH_SIZE]
        chunk_results = _convert_chunk_cloud(
            chunk, opts, api_key=api_key, cloud_url=cloud_url
        )
        all_results.extend(chunk_results)
    return all_results


def _convert_chunk_cloud(
    pdf_paths: list[Path],
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str,
) -> list[ConvertResult]:
    """Process a single batch chunk of PDFs via cloud API."""
    import concurrent.futures

    t0 = time.time()
    out_dir = opts.output_dir if opts.output_dir else pdf_paths[0].parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build per-file results and output paths
    results: dict[str, ConvertResult] = {}
    data_id_to_path: dict[str, Path] = {}
    files_payload = []

    for pdf_path in pdf_paths:
        data_id = pdf_path.stem
        md_path = out_dir / (pdf_path.stem + ".md")
        result = ConvertResult(pdf_path=pdf_path, md_path=md_path)

        if md_path.exists() and not opts.force:
            _log.debug("skip (already exists): %s", md_path.name)
            result.success = True
            results[data_id] = result
            continue

        results[data_id] = result
        data_id_to_path[data_id] = pdf_path
        files_payload.append({"name": pdf_path.name, "data_id": data_id})

    if not files_payload:
        return list(results.values())

    # Step 1: request signed upload URLs for all files
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "files": files_payload,
        "model_version": opts.backend,
        "enable_formula": opts.formula_enable,
        "enable_table": opts.table_enable,
        "language": opts.lang,
    }
    if opts.parse_method == "ocr":
        payload["is_ocr"] = True

    try:
        resp = requests.post(
            f"{cloud_url}/file-urls/batch",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        for did in data_id_to_path:
            results[did].error = f"�?API 请求失败: {e}"
            results[did].elapsed_seconds = time.time() - t0
        return list(results.values())

    if resp.status_code != 200:
        for did in data_id_to_path:
            results[did].error = f"�?API HTTP {resp.status_code}: {resp.text[:200]}"
            results[did].elapsed_seconds = time.time() - t0
        return list(results.values())

    try:
        resp_data = resp.json()
    except ValueError:
        for did in data_id_to_path:
            results[did].error = "�?API 返回�?JSON 响应"
            results[did].elapsed_seconds = time.time() - t0
        return list(results.values())

    if resp_data.get("code") != 0:
        for did in data_id_to_path:
            results[did].error = f"�?API 错误: {resp_data.get('msg', resp.text[:200])}"
            results[did].elapsed_seconds = time.time() - t0
        return list(results.values())

    batch_data = resp_data.get("data", {})
    batch_id = batch_data.get("batch_id", "")
    file_urls = batch_data.get("file_urls", [])

    if len(file_urls) != len(files_payload):
        for did in data_id_to_path:
            results[
                did
            ].error = (
                f"�?API 返回 URL 数量不匹�? {len(file_urls)} vs {len(files_payload)}"
            )
            results[did].elapsed_seconds = time.time() - t0
        return list(results.values())

    # Step 2: parallel upload all PDFs
    ordered_data_ids = [f["data_id"] for f in files_payload]

    def _upload_one(idx: int) -> str | None:
        did = ordered_data_ids[idx]
        url = (
            file_urls[idx]
            if isinstance(file_urls[idx], str)
            else file_urls[idx].get("url", "")
        )
        pdf_path = data_id_to_path[did]
        try:
            with open(pdf_path, "rb") as f:
                put_resp = requests.put(url, data=f, timeout=120)
            if put_resp.status_code not in (200, 201):
                return f"HTTP {put_resp.status_code}"
        except requests.RequestException as e:
            return str(e)
        return None

    _log.info(
        "Uploading %d PDFs to MinerU cloud (batch %s)...",
        len(files_payload),
        batch_id[:12],
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        upload_errors = list(pool.map(_upload_one, range(len(files_payload))))

    for idx, err in enumerate(upload_errors):
        if err:
            did = ordered_data_ids[idx]
            results[did].error = f"PDF 上传失败: {err}"
            results[did].elapsed_seconds = time.time() - t0

    pending_ids = {
        did for idx, did in enumerate(ordered_data_ids) if not upload_errors[idx]
    }
    if not pending_ids:
        return list(results.values())

    _log.info("All uploaded, waiting for cloud parsing (%d files)...", len(pending_ids))

    # Step 3: poll for all results
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + CLOUD_TIMEOUT
    done_ids: set[str] = set()

    while time.time() < deadline and done_ids != pending_ids:
        time.sleep(CLOUD_POLL_INTERVAL)
        try:
            poll_resp = requests.get(
                f"{cloud_url}/extract-results/batch/{batch_id}",
                headers=poll_headers,
                timeout=30,
            )
        except requests.RequestException:
            continue

        if poll_resp.status_code != 200:
            continue
        try:
            poll_data = poll_resp.json()
        except ValueError:
            continue
        if poll_data.get("code") != 0:
            continue

        extract_results = poll_data.get("data", {}).get("extract_result", [])
        running_count = 0
        for item in extract_results:
            did = item.get("data_id", "")
            if did not in pending_ids or did in done_ids:
                continue
            state = item.get("state", "")

            if state == "done":
                # Per-file output dir for images etc.
                file_out_dir = out_dir / did
                file_out_dir.mkdir(parents=True, exist_ok=True)
                md_content = _download_cloud_result(item, file_out_dir)
                if md_content is None:
                    results[did].error = "无法从云端结果提�?Markdown"
                else:
                    md_path = results[did].md_path
                    md_path.write_text(md_content, encoding="utf-8")
                    # Move assets from per-file subdir to out_dir (flat)
                    _flatten_assets(file_out_dir, out_dir, did)
                    results[did].success = True
                    results[did].md_size = len(md_content.encode("utf-8"))
                    _log.info(
                        "-> [cloud] %s (%s)",
                        md_path.name,
                        _fmt_size(results[did].md_size),
                    )
                results[did].elapsed_seconds = time.time() - t0
                done_ids.add(did)

            elif state == "failed":
                results[did].error = f"云端解析失败: {item.get('err_msg', 'unknown')}"
                results[did].elapsed_seconds = time.time() - t0
                done_ids.add(did)

            elif state == "running":
                running_count += 1

        if running_count and not done_ids - pending_ids:
            done_count = len(done_ids)
            _log.info(
                "Cloud parsing: %d/%d done, %d running...",
                done_count,
                len(pending_ids),
                running_count,
            )

    # Mark timed-out files
    for did in pending_ids - done_ids:
        results[did].error = f"云端解析超时（{CLOUD_TIMEOUT}s�?
        results[did].elapsed_seconds = time.time() - t0

    elapsed = time.time() - t0
    ok = sum(1 for did in pending_ids if results[did].success)
    _log.info(
        "Batch done: %d/%d succeeded (%.1fs total)", ok, len(pending_ids), elapsed
    )

    return list(results.values())


def _flatten_assets(src_dir: Path, out_dir: Path, data_id: str) -> None:
    """Move images/ and other assets from per-file subdir to out_dir, namespaced by data_id."""
    images_src = src_dir / "images"
    if images_src.is_dir():
        # Move entire images dir, namespaced to avoid collisions
        images_dst = out_dir / f"{data_id}_images"
        if images_dst.exists():
            import shutil

            shutil.rmtree(str(images_dst))
        images_src.rename(images_dst)

    # Move other assets (layout.json, content_list.json, origin.pdf)
    for f in src_dir.iterdir():
        if f.is_file():
            dest = out_dir / f"{data_id}_{f.name}"
            f.rename(dest)

    # Clean up empty subdir
    try:
        src_dir.rmdir()
    except OSError:
        pass


def _download_cloud_result(item: dict, out_dir: Path) -> str | None:
    """Download markdown (and images) from cloud API result.

    Tries multiple response formats: direct md_content field,
    full_zip_url (download zip and extract all files), or md_url.

    CDN download bypasses HTTP proxy (domestic CDN + proxy = SSL errors).

    Args:
        item: Single extract result dict from cloud API.
        out_dir: Directory to extract images and other assets into.

    Returns:
        Markdown text, or ``None`` on failure.
    """
    # Direct markdown content
    md = item.get("md_content")
    if isinstance(md, str) and md.strip():
        return md

    # Download zip and extract all files (md + images/)
    zip_url = item.get("full_zip_url")
    if zip_url:
        try:
            import io
            import zipfile

            # Bypass proxy for CDN downloads (domestic CDN through proxy causes SSL errors)
            resp = requests.get(
                zip_url, timeout=120, proxies={"http": None, "https": None}
            )
            if resp.status_code == 200:
                md_content = None
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    for name in zf.namelist():
                        if name.endswith("/"):
                            continue
                        if name.endswith(".md"):
                            md_content = zf.read(name).decode("utf-8")
                        else:
                            # Extract all assets (images/, layout.json, etc.)
                            dest = out_dir / name
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(zf.read(name))
                return md_content
        except Exception as e:
            _log.debug("failed to download/extract zip result: %s", e)

    # Direct markdown URL
    md_url = item.get("md_url")
    if md_url:
        try:
            resp = requests.get(
                md_url, timeout=60, proxies={"http": None, "https": None}
            )
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            _log.debug("failed to download markdown from %s: %s", md_url, e)

    return None


# ============================================================================
#  Utilities
# ============================================================================


def _fmt_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    elif nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    else:
        return f"{nbytes / (1024 * 1024):.1f} MB"


# ============================================================================
#  CLI Commands
# ============================================================================


