import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from pipeline import process_audio

app = FastAPI(
    title="ClassPart Audio Service",
    description="Processes seminar recordings into identified speaker transcripts.",
)


@app.get("/")
def root():
    return {"message": "ClassPart Audio Service is running"}


@app.post("/process-audio")
async def process_audio_endpoint(audio: Annotated[UploadFile, File(...)]):
    # Keep the original extension if possible
    suffix = Path(audio.filename or "recording.wav").suffix

    if not suffix:
        suffix = ".wav"

    temp_path = None

    try:
        # Create a temporary audio file
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:
            temp_path = Path(temp_file.name)

            # Copy uploaded audio into temporary file
            shutil.copyfileobj(
                audio.file,
                temp_file,
            )

        print(f"Received audio: {audio.filename}")
        print(f"Temporary file: {temp_path}")

        # Run your EXISTING pipeline
        result = process_audio(str(temp_path))

        # Return result to frontend as JSON
        return result

    except Exception as e:
        print(f"Audio processing failed: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e),
        ) from e

    finally:
        # Close uploaded file
        await audio.close()

        # Remove temporary recording
        if temp_path and temp_path.exists():
            temp_path.unlink()
