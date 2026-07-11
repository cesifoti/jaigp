"""Re-generate HTML/Markdown reading artifacts for existing papers.

Runs the PyMuPDF converter first (refreshes extracted images + placeholder with
heading detection), then the Claude-based AI converter which overwrites the
placeholder. Sequential, one paper at a time.

Usage:
    venv/bin/python scripts/reconvert_papers.py            # all papers, current versions
    venv/bin/python scripts/reconvert_papers.py --paper-id 26
    venv/bin/python scripts/reconvert_papers.py --limit 3  # smoke test
    venv/bin/python scripts/reconvert_papers.py --local-only  # skip the AI pass
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import SessionLocal
from models.paper import Paper, PaperVersion
from services.file_storage import file_storage
from services.pdf_converter import pdf_converter
from services.ai_converter import ai_converter


async def reconvert(paper: Paper, pv: PaperVersion, local_only: bool) -> str:
    pdf_path = file_storage.get_file_path(pv.pdf_filename, paper.published_date)
    if not pdf_path.exists():
        return "missing-pdf"

    base_path = str(pdf_path).rsplit(".", 1)[0]
    try:
        pdf_converter.save_converted_formats(
            str(pdf_path), base_path, paper.title, paper.abstract or ""
        )
    except Exception as e:
        print(f"  ! PyMuPDF conversion failed: {e!r}")

    if local_only:
        return "local"

    try:
        await ai_converter.save_ai_formats(str(pdf_path), base_path, paper.title)
        return "ai"
    except Exception as e:
        print(f"  ! AI conversion failed (placeholder kept): {e!r}")
        return "ai-failed"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", type=int, help="Convert a single paper")
    parser.add_argument("--limit", type=int, help="Stop after N papers")
    parser.add_argument("--local-only", action="store_true", help="Skip the AI pass")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Paper).order_by(Paper.id)
        if args.paper_id:
            q = q.filter(Paper.id == args.paper_id)
        papers = q.all()

        results = {}
        done = 0
        for paper in papers:
            if args.limit and done >= args.limit:
                break
            pv = db.query(PaperVersion).filter(
                PaperVersion.paper_id == paper.id,
                PaperVersion.version_number == paper.current_version,
            ).first()
            if not pv:
                continue
            done += 1
            t0 = time.monotonic()
            print(f"[{done}] paper {paper.id} v{pv.version_number}: {paper.title[:60]}")
            outcome = await reconvert(paper, pv, args.local_only)
            results[outcome] = results.get(outcome, 0) + 1
            print(f"    -> {outcome} in {time.monotonic() - t0:.1f}s")

        print(f"\nDone: {results}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
