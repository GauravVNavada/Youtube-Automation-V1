from __future__ import annotations

from pathlib import Path


def synthesize_google_tts(
    text: str,
    output_path: Path,
    credentials_path: str,
    speaking_rate: float | None = None,
) -> str:
    """Generate real narration with Google Cloud Text-to-Speech."""
    if not credentials_path:
        raise RuntimeError("GOOGLE_TTS_CREDENTIALS is not configured")
    if not Path(credentials_path).exists():
        raise RuntimeError(f"Google TTS credentials file does not exist: {credentials_path}")

    try:
        from google.cloud import texttospeech
    except ModuleNotFoundError as exc:
        raise RuntimeError("google-cloud-texttospeech is not installed") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    client = texttospeech.TextToSpeechClient.from_service_account_json(credentials_path)
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Neural2-D",
    )
    audio_config_kwargs = {"audio_encoding": texttospeech.AudioEncoding.LINEAR16}
    if speaking_rate is not None:
        audio_config_kwargs["speaking_rate"] = max(0.25, min(4.0, float(speaking_rate)))
    audio_config = texttospeech.AudioConfig(**audio_config_kwargs)
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    output_path.write_bytes(response.audio_content)
    if output_path.stat().st_size < 1024:
        raise RuntimeError("Google TTS returned an unusably small audio file")
    return str(output_path)
