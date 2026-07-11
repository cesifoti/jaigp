"""AI-powered PDF -> Markdown/HTML conversion via the Claude API.

Produces reading-oriented artifacts: structured Markdown with LaTeX math in
KaTeX-compatible delimiters, real (text) tables, and figure references into the
already-extracted {basename}_images/ directory. The PyMuPDF converter
(services/pdf_converter.py) remains the fast placeholder and the fallback when
the API is unavailable.
"""
import asyncio
import base64
import html as html_mod
import os
import re
from pathlib import Path

import markdown as md_lib

import config
from services.pdf_converter import pdf_converter

MODEL = "claude-opus-4-8"
MAX_OUTPUT_TOKENS = 64000

# Keep strong references to fire-and-forget conversion tasks so they aren't GC'd
_BACKGROUND_TASKS: set = set()

_SYSTEM_PROMPT = """You convert academic paper PDFs into faithful, well-structured GitHub-flavored Markdown for a journal's web reading view.

Rules:
- Reproduce the paper's full text verbatim — do not summarize, paraphrase, or omit content. Repair PDF artifacts only: rejoin hyphenated line breaks, fix ligatures, drop running headers/footers and page numbers.
- Structure: `#` for the paper title, `##` for top-level sections (keep the paper's own numbering, e.g. `## 2 Background`), `###`/`####` for subsections. Include the abstract under `## Abstract`.
- Math: use LaTeX — display equations in `$$ ... $$` on their own lines, inline math as `\\( ... \\)`. Preserve equation numbers like `\\tag{3}` inside display math when the paper numbers its equations.
- Tables: reconstruct as Markdown tables (use HTML <table> markup only when merged cells make Markdown impossible). Include the table caption as italic text above the table.
- Figures: you are given an inventory of image files extracted from the PDF, listed in document order. Where each figure appears, insert `![CAPTION](__IMG__/FILENAME)` followed by the figure caption in italics. Files named `table_N.png` are rasterized tables — prefer reconstructing those as text tables and do not reference the image unless reconstruction is impossible.
- Footnotes: gather as a `## Footnotes` section before References, numbered to match in-text markers.
- References: include the complete reference list verbatim under `## References`, one entry per line as a numbered or bulleted list matching the paper's style.
- Output ONLY the Markdown document. No preamble, no commentary, no code fences around the output."""


class AIConverter:
    """Convert PDFs to Markdown/HTML using Claude."""

    def _figure_inventory(self, image_dir: str) -> list:
        if not os.path.isdir(image_dir):
            return []
        return sorted(
            f for f in os.listdir(image_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
        )

    async def pdf_to_markdown(self, pdf_path: str, paper_title: str) -> str:
        """Convert a PDF to structured Markdown via the Claude API.

        Raises on API failure or truncated output — callers fall back to the
        PyMuPDF converter's artifacts.
        """
        import anthropic

        pdf_dir = os.path.dirname(pdf_path)
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        image_dir = os.path.join(pdf_dir, f"{pdf_basename}_images")
        figures = self._figure_inventory(image_dir)

        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

        inventory = (
            "Extracted image files (document order): " + ", ".join(figures)
            if figures else
            "No image files were extracted from this PDF; do not emit any image references."
        )
        user_text = (
            f'Convert this paper ("{paper_title}") to Markdown following your rules.\n{inventory}'
        )

        client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }],
        ) as stream:
            message = await stream.get_final_message()

        if message.stop_reason == "max_tokens":
            raise RuntimeError(f"AI conversion truncated at {MAX_OUTPUT_TOKENS} tokens")

        md_text = "".join(b.text for b in message.content if b.type == "text").strip()
        # Strip an accidental fence despite instructions
        md_text = re.sub(r'^```(?:markdown)?\s*\n', '', md_text)
        md_text = re.sub(r'\n```\s*$', '', md_text)
        if len(md_text) < 500:
            raise RuntimeError("AI conversion produced implausibly short output")

        # Resolve image placeholder to the real relative directory
        md_text = md_text.replace("__IMG__/", f"{pdf_basename}_images/")
        return md_text

    # ------------------------------------------------------------------
    # Markdown -> standalone HTML artifact
    # ------------------------------------------------------------------

    _MATH_RE = re.compile(r'\$\$.*?\$\$|\\\(.*?\\\)|\\\[.*?\\\]', re.S)

    def markdown_to_html(self, md_text: str, paper_title: str) -> str:
        """Render Markdown to the standalone HTML artifact.

        LaTeX segments are shielded from the Markdown parser (underscores etc.)
        and re-inserted HTML-escaped; KaTeX renders them client-side from the
        $$ / \\( delimiters.
        """
        segments = []

        def _shield(m):
            segments.append(m.group(0))
            # Alphanumeric placeholder: python-markdown uses STX/ETX control
            # chars internally and eats them, so those are NOT safe here
            return f"MATHSEGQQ{len(segments) - 1}QQGESHTAM"

        shielded = self._MATH_RE.sub(_shield, md_text)
        body = md_lib.markdown(
            shielded,
            extensions=["tables", "fenced_code", "sane_lists"],
        )
        for i, seg in enumerate(segments):
            body = body.replace(f"MATHSEGQQ{i}QQGESHTAM", html_mod.escape(seg, quote=False))

        title = html_mod.escape(paper_title)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.7; color: #1e293b; }}
h1, h2, h3, h4 {{ font-family: -apple-system, 'Segoe UI', sans-serif; line-height: 1.3; }}
img {{ max-width: 100%; height: auto; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
th, td {{ border: 1px solid #cbd5e1; padding: 0.4rem 0.6rem; }}
</style>
</head>
<body>
{body}
<hr>
<p><em>This reading version was generated from the PDF by an AI conversion pipeline; the PDF remains the version of record.</em></p>
</body>
</html>"""

    async def save_ai_formats(self, pdf_path: str, base_path: str, paper_title: str) -> bool:
        """Convert via Claude and overwrite {base_path}.md / {base_path}.html.

        Returns True on success. On failure the PyMuPDF artifacts are left alone.
        """
        md_text = await self.pdf_to_markdown(pdf_path, paper_title)
        html_text = self.markdown_to_html(md_text, paper_title)

        with open(f"{base_path}.md", "w", encoding="utf-8") as f:
            f.write(md_text)
        with open(f"{base_path}.html", "w", encoding="utf-8") as f:
            f.write(html_text)
        print(f"✓ AI-generated Markdown/HTML: {base_path}.md")
        return True


async def convert_formats_background(pdf_path: str, base_path: str,
                                     paper_title: str, paper_abstract: str) -> None:
    """Background conversion pipeline for a freshly uploaded PDF.

    Stage 1: fast PyMuPDF conversion so HTML/MD links work within seconds.
    Stage 2: Claude conversion; overwrites the placeholders when it succeeds.
    """
    try:
        await asyncio.to_thread(
            pdf_converter.save_converted_formats,
            pdf_path, base_path, paper_title, paper_abstract,
        )
    except Exception as e:
        print(f"[convert] PyMuPDF conversion failed for {pdf_path}: {e!r}")

    # Author-provided LaTeX source produces the best HTML — use it when present
    from services.latex_converter import convert_latex_source, source_path_for
    source_path = source_path_for(base_path)
    if source_path:
        try:
            await asyncio.to_thread(convert_latex_source, source_path, base_path)
            # Still generate the AI Markdown (LaTeXML only replaces the HTML view)
            try:
                md_text = await ai_converter.pdf_to_markdown(pdf_path, paper_title)
                with open(f"{base_path}.md", "w", encoding="utf-8") as f:
                    f.write(md_text)
            except Exception as e:
                print(f"[convert] AI markdown failed for {pdf_path}: {e!r}")
            return
        except Exception as e:
            print(f"[convert] LaTeXML conversion failed for {source_path}, "
                  f"falling back to AI conversion: {e!r}")

    try:
        await ai_converter.save_ai_formats(pdf_path, base_path, paper_title)
    except Exception as e:
        print(f"[convert] AI conversion failed for {pdf_path} (keeping PyMuPDF version): {e!r}")


def schedule_conversion(pdf_path: str, base_path: str,
                        paper_title: str, paper_abstract: str) -> None:
    """Fire-and-forget conversion; falls back to inline conversion outside an event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pdf_converter.save_converted_formats(pdf_path, base_path, paper_title, paper_abstract)
        return
    task = loop.create_task(
        convert_formats_background(pdf_path, base_path, paper_title, paper_abstract)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


ai_converter = AIConverter()
