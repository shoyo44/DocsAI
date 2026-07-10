"""
OCR Pipeline — multi-tier text extraction for scanned or image-heavy PDFs.

Optimized version:
1. Reuses a single fitz.Document handle across all page operations.
2. Parallelizes OCR extraction and image description using asyncio.gather with Semaphore.
3. Compresses pixmap bytes to JPEG (80% quality) instead of PNG to minimize network payloads.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import fitz   # PyMuPDF

logger = logging.getLogger("docqa.ocr")


# ─── Tier 1: PyMuPDF native text ─────────────────────────────────────────────

def _extract_page_tables_as_markdown(file_path: str, page_num: int) -> str:
    """
    Extract tables on a page using pdfplumber and return them as formatted Markdown tables.
    """
    try:
        import pdfplumber
        markdown_tables = []
        with pdfplumber.open(file_path) as pdf:
            if page_num < len(pdf.pages):
                page = pdf.pages[page_num]
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        rows = []
                        for r in table:
                            if any(cell is not None and str(cell).strip() for cell in r):
                                rows.append([str(cell or "").replace("\n", " ").strip() for cell in r])
                        
                        if not rows:
                            continue
                        
                        col_count = max(len(r) for r in rows)
                        headers = rows[0]
                        header_line = "| " + " | ".join(headers + [""] * (col_count - len(headers))) + " |"
                        separator_line = "| " + " | ".join(["---"] * col_count) + " |"
                        
                        md_rows = []
                        for row in rows[1:]:
                            row_line = "| " + " | ".join(row + [""] * (col_count - len(row))) + " |"
                            md_rows.append(row_line)
                        
                        md_table = "\n".join([header_line, separator_line] + md_rows)
                        markdown_tables.append(f"\n[TABLE CONTENT]:\n{md_table}\n")
        return "\n".join(markdown_tables) if markdown_tables else ""
    except Exception as exc:
        logger.debug("pdfplumber table extraction failed page %d: %s", page_num + 1, exc)
        return ""


def extract_pages_native(doc: fitz.Document, file_path: str) -> List[Dict[str, Any]]:
    """
    Extract text and layout tables from each page.
    Fast and accurate for digital (non-scanned) PDFs.
    Returns pages where text extraction yielded at least 50 characters.
    """
    pages = []
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        
        # Merge layout-aware table markdown
        tables_md = _extract_page_tables_as_markdown(file_path, i)
        if tables_md:
            text += "\n" + tables_md

        if len(text) >= 50:
            pages.append({"page": i + 1, "text": text, "ocr_used": False})
    return pages


# ─── Tier 2: PyTesseract (local OCR) ─────────────────────────────────────────

def _ocr_page_tesseract(page: fitz.Page) -> Optional[str]:
    """OCR a single page with PyTesseract. Returns text or None on failure."""
    try:
        import pytesseract
        from PIL import Image
        # Render at 300 DPI for good OCR accuracy
        mat  = fitz.Matrix(300 / 72, 300 / 72)
        pix  = page.get_pixmap(matrix=mat)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img, lang="eng")
        return text.strip() if len(text.strip()) >= 30 else None
    except Exception as exc:
        logger.debug("Tesseract failed page %d: %s", page.number + 1, exc)
        return None


# ─── Tier 3: AWS Textract ─────────────────────────────────────────────────────

def _ocr_page_textract(page: fitz.Page) -> Optional[str]:
    """OCR a single page with AWS Textract. Returns text or None."""
    try:
        import boto3
        mat  = fitz.Matrix(2.0, 2.0)
        pix  = page.get_pixmap(matrix=mat)
        image_bytes = pix.tobytes("jpeg", jpg_quality=80)  # JPEG compression

        client   = boto3.client("textract", region_name=os.getenv("AWS_REGION", "us-east-1"))
        response = client.detect_document_text(Document={"Bytes": image_bytes})
        lines    = [
            b["Text"] for b in response["Blocks"]
            if b["BlockType"] == "LINE"
        ]
        return "\n".join(lines) if lines else None
    except Exception as exc:
        logger.debug("Textract failed page %d: %s", page.number + 1, exc)
        return None


# ─── Tier 3.2: OCR.space API ─────────────────────────────────────────────────

async def _ocr_page_ocr_space(page: fitz.Page) -> Optional[str]:
    """OCR a single page with OCR.space API. Returns text or None."""
    api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld")
    try:
        import httpx
        mat  = fitz.Matrix(2.0, 2.0)
        pix  = page.get_pixmap(matrix=mat)
        image_bytes = pix.tobytes("jpeg", jpg_quality=80)  # JPEG compression

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.ocr.space/parse/image",
                data={
                    "apikey": api_key,
                    "language": "eng",
                    "isOverlayRequired": "false"
                },
                files={
                    "file": ("page.jpg", image_bytes, "image/jpeg")
                }
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("IsErroredOnProcessing"):
                logger.warning(
                    "OCR.space API error on page %d: %s",
                    page.number + 1,
                    data.get("ErrorMessage")
                )
                return None

            results = data.get("ParsedResults")
            if results and len(results) > 0:
                parsed_text = results[0].get("ParsedText", "").strip()
                return parsed_text if len(parsed_text) >= 30 else None
            
            return None
    except Exception as exc:
        logger.debug("OCR.space API failed page %d: %s", page.number + 1, exc)
        return None


# ─── Tier 3.5: Cloudflare Workers AI Vision OCR ──────────────────────────────

async def _ocr_page_cloudflare_vision(
    page: fitz.Page,
    cf_client: Any,
) -> Optional[str]:
    """OCR a single page using Cloudflare Workers AI Vision model."""
    try:
        # Render at 200 DPI for text clarity on scanned pages
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat)
        image_bytes = pix.tobytes("jpeg", jpg_quality=80)  # JPEG compression

        prompt = (
            "This is a scanned page from an academic research paper. "
            "Read all the printed text exactly as it appears, line by line, top to bottom. "
            "Copy the text word-for-word with no paraphrasing, no summaries, no added commentary. "
            "If a line contains a heading, copy it as-is. "
            "If there is a paragraph, copy every sentence. "
            "Output ONLY the raw extracted text — nothing else."
        )
        text = await cf_client.describe_image(image_bytes, prompt=prompt)
        if not text:
            return None
        text = text.strip()
        
        # Hallucination guard: reject output that is clearly looping/repetitive
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 6:
            unique_ratio = len(set(lines)) / len(lines)
            if unique_ratio < 0.4:  # >60% duplicate lines = hallucination
                logger.warning(
                    "CF Vision OCR on page %d rejected: repetition ratio %.2f (likely hallucination)",
                    page.number + 1, 1 - unique_ratio,
                )
                return None
        if "unavailable" in text.lower() or "failed" in text.lower():
            return None
        return text if len(text) >= 30 else None
    except Exception as exc:
        logger.debug("Cloudflare Vision OCR failed page %d: %s", page.number + 1, exc)
        return None


# ─── Tier 4: Cloudflare Vision (images/charts) ───────────────────────────────

async def _describe_images_on_page(
    page: fitz.Page,
    cf_client: Any,
) -> Optional[str]:
    """
    Extract and describe embedded images/figures on a page using CF Vision.
    Returns a [VISUAL DESCRIPTION: ...] annotation string, or None if no images.
    """
    try:
        images = page.get_images(full=True)
        if not images:
            return None

        descriptions = []
        doc = page.parent
        for img_info in images[:3]:   # cap at 3 images per page
            xref     = img_info[0]
            img_data = doc.extract_image(xref)

            if img_data:
                # Downscale or compress image bytes to JPEG if they are too large
                img_bytes = img_data["image"]
                description = await cf_client.describe_image(img_bytes)
                if description and "unavailable" not in description.lower():
                    descriptions.append(f"[VISUAL DESCRIPTION: {description}]")

        return "\n".join(descriptions) if descriptions else None

    except Exception as exc:
        logger.debug("Vision description failed page %d: %s", page.number + 1, exc)
        return None


# ─── Main extraction entry point ─────────────────────────────────────────────

async def extract_pages(
    file_path: str,
    cf_client: Optional[Any] = None,
    use_ocr_fallback: bool = True,
) -> List[Dict[str, Any]]:
    """
    Extract all pages from a PDF with parallel execution and fitz.Document reuse.
    """
    doc = fitz.open(file_path)
    try:
        # Tier 1: Try native extraction first
        pages = extract_pages_native(doc, file_path)

        # Identify pages that are blank (likely scanned) or have very short native text (e.g. stamped metadata/header stamps)
        total_pages  = len(doc)
        blank_pages = []
        for i in range(total_pages):
            page_num = i + 1
            existing_native = next((p for p in pages if p["page"] == page_num), None)
            if not existing_native or len(existing_native["text"].strip()) < 300:
                blank_pages.append(i)

        # Tier 2+3+3.5: OCR blank/short pages concurrently with bounded Semaphore
        if use_ocr_fallback and blank_pages:
            logger.info("Running parallel OCR on %d candidate pages...", len(blank_pages))
            sem = asyncio.Semaphore(1)  # Bounded concurrency (lowered to 1 for Render 512MB RAM safety)

            async def ocr_task(page_num: int) -> Optional[Dict[str, Any]]:
                async with sem:
                    page = doc[page_num]
                    # Attempt Tesseract
                    text = await asyncio.to_thread(_ocr_page_tesseract, page)
                    if not text:
                        logger.info("Falling back to OCR.space API for page %d...", page_num + 1)
                        text = await _ocr_page_ocr_space(page)
                    if not text:
                        logger.info("Falling back to AWS Textract for page %d...", page_num + 1)
                        text = await asyncio.to_thread(_ocr_page_textract, page)
                    if not text and cf_client:
                        logger.info("Falling back to Cloudflare Workers AI Vision OCR for page %d...", page_num + 1)
                        text = await _ocr_page_cloudflare_vision(page, cf_client)
                    
                    if text:
                        return {
                            "page":     page_num + 1,
                            "text":     text,
                            "ocr_used": True,
                        }
                    return None

            ocr_jobs = [ocr_task(p_num) for p_num in blank_pages]
            ocr_results = await asyncio.gather(*ocr_jobs)
            for res in ocr_results:
                if res:
                    p_num = res["page"]
                    existing_native = next((p for p in pages if p["page"] == p_num), None)
                    if existing_native:
                        # Append OCR text below stamped native text
                        existing_native["text"] = (existing_native["text"] + "\n\n[OCR FALLBACK CONTENT]:\n" + res["text"]).strip()
                        existing_native["ocr_used"] = True
                    else:
                        pages.append(res)

        # Tier 4: Parallelize visual descriptions for all pages concurrently if cf_client exists
        if cf_client:
            sem_vision = asyncio.Semaphore(5)  # Limit concurrent vision requests

            async def vision_task(page_data: Dict[str, Any]) -> None:
                async with sem_vision:
                    page = doc[page_data["page"] - 1]
                    visual = await _describe_images_on_page(page, cf_client)
                    if visual:
                        page_data["enriched_text"] = page_data["text"] + "\n\n" + visual
                    else:
                        page_data["enriched_text"] = None

            vision_jobs = [vision_task(p_data) for p_data in pages]
            await asyncio.gather(*vision_jobs)
        else:
            for page_data in pages:
                page_data["enriched_text"] = None

        # Sort by page number
        pages.sort(key=lambda p: p["page"])
        logger.info(
            "Extracted %d pages from '%s' (%d OCR'd).",
            len(pages), os.path.basename(file_path),
            sum(1 for p in pages if p.get("ocr_used"))
        )
        return pages

    finally:
        doc.close()
