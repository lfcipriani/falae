"""HTTP API for Cloud Run. Run locally with: uvicorn falae.api:app --reload"""

from __future__ import annotations

import datetime as dt
import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import BackgroundTasks, Depends, FastAPI, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .auth import API_KEY_HEADER, AccessPolicy
from .languages import resolve_language
from .models import Article, InputFormat, SynthesisOptions
from .service import output_filename, synthesize_article
from .storage import Storage, storage_from_env
from .webhook import SUCCESS_MESSAGE, Webhook, webhook_from_env

log = logging.getLogger("falae")
# Uvicorn only configures its own loggers; without this, job outcomes never reach Cloud Logging.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@lru_cache(maxsize=1)
def get_access_policy() -> AccessPolicy:
    """One policy per process, from FALAE_API_KEY and FALAE_ALLOWED_IPS (see auth.py)."""
    policy = AccessPolicy.from_env()
    if policy.api_key is None:
        log.warning("FALAE_API_KEY is not set: /synthesize accepts requests without an API key")
    if policy.allowed_networks:
        log.info("only accepting requests from %s", ", ".join(map(str, policy.allowed_networks)))
    return policy


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Build both at startup so a bad setting (e.g. a malformed FALAE_ALLOWED_IPS) stops the
    # container from starting instead of failing every request.
    get_storage()
    get_access_policy()
    get_webhook()
    yield


app = FastAPI(title="falae", lifespan=lifespan)
_api_key = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def require_access(
    request: Request,
    key: str | None = Security(_api_key),
    policy: AccessPolicy = Depends(get_access_policy),
) -> None:
    """403 if the client IP isn't allowed, 401 if the API key is missing or wrong."""
    policy.check(request, key)


class SynthesizeRequest(BaseModel):
    language: str = Field(
        min_length=2,
        examples=["pt-BR", "en-US", "en"],
        description='BCP-47 locale, or a bare language such as "en" (resolved to en-US)',
    )
    content: str = Field(min_length=1, description="Article body in Markdown (plain text is fine)")
    title: str | None = None
    author: str | None = None
    published_date: dt.date | None = None
    link: str | None = Field(None, description="Not read aloud; stored in the MP3 metadata")
    takeaways: str | None = Field(None, description="Markdown, read before the article body")
    voice: str = "Charon"
    input_format: InputFormat = InputFormat.SSML
    speaking_rate: float = Field(1.0, ge=0.25, le=2.0)

    @model_validator(mode="before")
    @classmethod
    def _blank_means_unset(cls, data: object) -> object:
        """Callers like n8n send "" or null for empty fields. For optional fields, treat both
        (and whitespace-only strings) as not sent, so defaults apply. Required fields still 422."""
        if not isinstance(data, dict):
            return data
        optional = {name for name, f in cls.model_fields.items() if not f.is_required()}
        return {k: v for k, v in data.items()
                if not (k in optional and (v is None or (isinstance(v, str) and not v.strip())))}

    @field_validator("language")
    @classmethod
    def _resolve_language(cls, value: str) -> str:
        return resolve_language(value)  # ValueError becomes a 422

    @field_validator("published_date", mode="wrap")
    @classmethod
    def _lenient_date(cls, value: object, handler) -> dt.date | None:
        """A bad date only loses the byline date, so it's ignored instead of failing the request.
        ISO datetimes ("2026-11-15T10:30:00Z") are accepted and keep just the date."""
        try:
            return handler(value)
        except ValidationError:
            pass
        if isinstance(value, str):
            try:
                return dt.datetime.fromisoformat(value.strip()).date()
            except ValueError:
                pass
        log.warning("ignoring invalid published_date %r", value)
        return None


class SynthesizeAccepted(BaseModel):
    status: str = "accepted"
    location: str = Field(description="Where the MP3 will appear once synthesis finishes")


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """One storage per process, configured from the environment (FALAE_STORAGE, FALAE_GCS_BUCKET,
    FALAE_OUTPUT_DIR). Requests can't pick the destination."""
    return storage_from_env()


@lru_cache(maxsize=1)
def get_webhook() -> Webhook | None:
    """One webhook per process, from FALAE_WEBHOOK_URL; None when unset."""
    webhook = webhook_from_env()
    if webhook:
        log.info("job results will be posted to the webhook")
    return webhook


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def run_synthesis(article: Article, storage: Storage, options: SynthesisOptions,
                  webhook: Webhook | None = None) -> None:
    """Background job. The outcome is logged and, if configured, posted to the webhook."""
    filename = output_filename(article)
    try:
        result = synthesize_article(article, storage, options)
    except Exception as exc:
        log.exception("synthesis failed for %s", filename)
        if webhook:
            webhook.notify(storage.kind, storage.location_for(filename),
                           str(exc) or type(exc).__name__)
        return
    log.info("saved %s (%d chunks, %d billed chars, %d bytes)",
             result.location, result.chunks, result.characters, result.bytes)
    if webhook:
        webhook.notify(storage.kind, result.location, SUCCESS_MESSAGE)


@app.post("/synthesize", response_model=SynthesizeAccepted, status_code=status.HTTP_202_ACCEPTED,
          dependencies=[Depends(require_access)])
def synthesize(
    req: SynthesizeRequest,
    background: BackgroundTasks,
    storage: Storage = Depends(get_storage),
    webhook: Webhook | None = Depends(get_webhook),
) -> SynthesizeAccepted:
    """Validates the request and returns 202 right away. The MP3 is synthesized after the
    response is sent; check `location` for the file."""
    article = Article(
        language=req.language,
        content=req.content,
        title=req.title,
        author=req.author,
        published_date=req.published_date,
        link=req.link,
        takeaways=req.takeaways,
    )
    options = SynthesisOptions(
        voice=req.voice, input_format=req.input_format, speaking_rate=req.speaking_rate
    )
    # A plain-`def` task runs in the threadpool, so the blocking TTS/ffmpeg work doesn't stall the loop.
    background.add_task(run_synthesis, article, storage, options, webhook)
    return SynthesizeAccepted(location=storage.location_for(output_filename(article)))
