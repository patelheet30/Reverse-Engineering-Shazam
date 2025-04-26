import logging
import tempfile
from pathlib import Path

import config
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from main import identify_song

app = FastAPI()

logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/identify")
async def identify_audio(file: UploadFile = File(...), duration: float = 10.0):
    try:
        suffix = Path(file.filename).suffix  # type: ignore
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        db_base_path = str(config.DATABASE_DIR / config.DB_FILENAME)

        matches = identify_song(
            tmp_path,
            db_path=db_base_path,
            duration=duration,
            threshold=0.001,
            max_workers=4,
        )

        if not matches:
            raise HTTPException(status_code=404, detail="No matches found.")

        top_match = max(matches, key=lambda match: match.confidence)

        result = {
            "song_id": top_match.song_id,
            "song_name": top_match.song_name,
            "confidence": top_match.confidence,
            "offset": top_match.offset,
            "match_count": top_match.match_count,
        }

        return {"matches": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
