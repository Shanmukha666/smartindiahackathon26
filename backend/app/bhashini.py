"""Bhashini pipeline client for Indic text, speech recognition, and speech synthesis."""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from .observability import outbound_headers, stage

if TYPE_CHECKING:
    from .config import Settings


class BhashiniClient:
    """Small adapter around the Bhashini inference-pipeline API.

    Service IDs are deployment-specific.  Leaving them unset lets Bhashini select
    the configured/default service for the requested language pair.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.bhashini_api_key:
            raise RuntimeError("BHASHINI_API_KEY must be set for Indic language services")
        self._url = settings.bhashini_api_url
        self._headers = {
            "Authorization": settings.bhashini_api_key.get_secret_value(),
            "Content-Type": "application/json",
        }
        if settings.bhashini_user_id:
            self._headers["userID"] = settings.bhashini_user_id
        self._client = client

    async def _run(self, task: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None:
            with stage("translation", provider="bhashini", task_type=str(task["taskType"])):
                response = await self._client.post(self._url, headers=outbound_headers(self._headers),
                                                   json={"pipelineTasks": [task], "inputData": input_data})
                response.raise_for_status()
            return cast(dict[str, Any], response.json())
        async with httpx.AsyncClient(timeout=30) as client:
            with stage("translation", provider="bhashini", task_type=str(task["taskType"])):
                response = await client.post(self._url, headers=outbound_headers(self._headers),
                                             json={"pipelineTasks": [task], "inputData": input_data})
                response.raise_for_status()
            return cast(dict[str, Any], response.json())

    @staticmethod
    def _output(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return cast(dict[str, Any], payload["pipelineResponse"][0]["output"][0])
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("Bhashini returned an unexpected pipeline response") from error

    async def translate(self, text: str, source_language: str, target_language: str = "en") -> str:
        if source_language == target_language:
            return text
        task: dict[str, Any] = {
            "taskType": "translation",
            "config": {"language": {"sourceLanguage": source_language, "targetLanguage": target_language}},
        }
        payload = await self._run(task, {"input": [{"source": text}]})
        translated = self._output(payload).get("target")
        if not isinstance(translated, str) or not translated.strip():
            raise RuntimeError("Bhashini did not return translated text")
        return translated

    async def transcribe(self, audio_base64: str, language: str) -> str:
        task = {"taskType": "asr", "config": {"language": {"sourceLanguage": language}}}
        payload = await self._run(task, {"audio": [{"audioContent": audio_base64}]})
        text = self._output(payload).get("source")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Bhashini did not return a transcript")
        return text

    async def synthesize(self, text: str, language: str) -> tuple[str, str]:
        task = {"taskType": "tts", "config": {"language": {"sourceLanguage": language}}}
        payload = await self._run(task, {"input": [{"source": text}]})
        output = self._output(payload)
        audio = output.get("audioContent")
        if not isinstance(audio, str):
            raise RuntimeError("Bhashini did not return synthesized audio")  # noqa: TRY004
        # Validate before returning an API response that embeds provider data.
        try:
            base64.b64decode(audio, validate=True)
        except (ValueError, binascii.Error) as error:
            raise RuntimeError("Bhashini returned invalid synthesized audio") from error
        return audio, str(output.get("audioFormat", "wav"))


IndicLanguage = Literal["en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te", "ur"]
