"""One-time backfill: translate existing Dutch summaries and stances to English."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.plenary_session import PlenarySession
from app.services.translation_service import translate_summary, translate_stances


async def backfill() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PlenarySession))
        sessions = list(result.scalars().all())

        print(f"Found {len(sessions)} sessions total")

        for s in sessions:
            needs_summary = s.summary and not s.summary_en
            needs_stances = s.stances and not s.stances_en

            if not needs_summary and not needs_stances:
                print(f"[SKIP] {s.id} — already translated or no content")
                continue

            print(f"[TRANSLATING] {s.id} ({s.title or 'untitled'})")

            if needs_summary:
                try:
                    s.summary_en = await translate_summary(s.summary)
                    print(f"  ✓ summary_en saved")
                except Exception as e:
                    print(f"  ✗ summary translation failed: {e}")

            if needs_stances:
                try:
                    s.stances_en = await translate_stances(json.loads(s.stances))
                    print(f"  ✓ stances_en saved")
                except Exception as e:
                    print(f"  ✗ stances translation failed: {e}")

            await db.flush()

        await db.commit()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(backfill())
