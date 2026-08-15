"""
One-time backfill: attach speaker_id to stances extracted before the speakers table
existed, and eagerly enrich those speakers (party names + photo) rather than waiting
for a first click on the detail page.

Usage:
    python scripts/backfill_speaker_ids.py           # all sessions with stances
    python scripts/backfill_speaker_ids.py --limit 3 # only the N most recent sessions (by date)
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.plenary_session import PlenarySession
from app.services.speaker_service import enrich_speaker, get_or_create_speaker


async def backfill(limit: int | None) -> None:
    async with AsyncSessionLocal() as db:
        query = select(PlenarySession).where(PlenarySession.stances.isnot(None))
        query = query.order_by(PlenarySession.date.desc().nulls_last())
        if limit:
            query = query.limit(limit)

        result = await db.execute(query)
        sessions = list(result.scalars().all())

        print(f"Processing {len(sessions)} session(s){f' (limit={limit})' if limit else ''}")

        for s in sessions:
            data = json.loads(s.stances)
            stances = data.get("stances", [])
            if not stances or all(st.get("speaker_id") is not None for st in stances):
                print(f"[SKIP] {s.id} — already backfilled or empty")
                continue

            print(f"[BACKFILLING] {s.id} ({s.title or 'untitled'}) — {len(stances)} stances")

            data_en = json.loads(s.stances_en) if s.stances_en else None
            stances_en = data_en.get("stances", []) if data_en else []

            for i, stance in enumerate(stances):
                if stance.get("speaker_id") is not None:
                    continue
                speaker_row = await get_or_create_speaker(db, stance.get("speaker"), stance.get("party"))
                if speaker_row is None:
                    stance["speaker_id"] = None
                    continue

                if speaker_row.resolved_at is None:
                    try:
                        speaker_row = await enrich_speaker(db, speaker_row)
                        print(f"    enriched: {speaker_row.name} ({speaker_row.party_afkorting}) -> {speaker_row.party_name_nl or 'no party match'}, photo={'yes' if speaker_row.image_path else 'no'}")
                    except Exception as e:
                        print(f"    ✗ enrichment failed for {speaker_row.name}: {e}")

                stance["speaker_id"] = speaker_row.id
                if i < len(stances_en):
                    stances_en[i]["speaker_id"] = speaker_row.id

            s.stances = json.dumps(data, ensure_ascii=False)
            if data_en:
                s.stances_en = json.dumps(data_en, ensure_ascii=False)

            await db.flush()
            print(f"  ✓ speaker_id attached")

        await db.commit()
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only backfill the N most recent sessions")
    args = parser.parse_args()
    asyncio.run(backfill(args.limit))
