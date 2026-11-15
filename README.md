# falae

falae turns an article into a single narrated MP3. It uses Google Cloud Text-to-Speech with Chirp 3 HD voices.

## Design decisions

- **Synchronous `synthesize` calls, splitting the text and joining the audio.**
  - Each request is limited to 5,000 bytes, and Google won't raise that limit. An average article (6–15 KB) takes about 2–4 requests.
  - Rejected alternatives:
    - **Long Audio Synthesis:** Pre-GA and WAV-only examples.
    - **Streaming:** no MP3 output.
    - **Gemini-TTS:** 4 KB per request, output cut off after about 11 minutes, and the voice can drift between chunks.
- **Chirp 3 HD voices.**
  - Google's top GA voice tier that isn't LLM-based, and the voice stays the same across chunks.
  - $30 per 1M characters, with the first 1M characters each month free. That's about $0.30 for a 10k-character article.
  - Every SSML tag counts toward the billed characters.
- **Minimal SSML.**
  - Only `<p>`, `<break>` and `<say-as>` (for the date) are used, plus `<prosody>` if you set it in `styles.py`. SSML is still Preview for Chirp 3 HD.
  - If SSML misbehaves, set `input_format: markup` to use GA pause tags instead.
- **Docs:**
  - [Chirp 3 HD](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd)
  - [quotas](https://docs.cloud.google.com/text-to-speech/quotas)
  - [pricing](https://cloud.google.com/text-to-speech/pricing)

## Architecture

```
            ┌─────────────┐     ┌──────────────┐
 request →  │ api.py      │     │ falae_cli.py │  ← local testing
 (HTTP)     │ FastAPI     │     │ argparse     │
            └──────┬──────┘     └──────┬───────┘
                   └─────────┬─────────┘
                             ▼
                   ┌───────────────────┐
                   │ service.py        │  orchestrates the pipeline
                   └─────────┬─────────┘
       ┌───────────────┬─────┴─────────┬───────────────┐
       ▼               ▼               ▼               ▼
 ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌────────────┐
 │ markdown  │ → │ tts.py    │ → │ audio.py  │ → │ storage.py │
 │ + text.py │   │ Chirp 3HD │   │ ffmpeg    │   │ local / GCS│
 │ → chunks  │   │ → MP3s    │   │ concat    │   │ / Dropbox  │
 └───────────┘   └───────────┘   └───────────┘   └────────────┘
```

### Pipeline

1. **Input** (`models.py`)

   | Field | Required | Notes |
   |---|---|---|
   | `language` | yes | BCP-47 locale, e.g. `pt-BR`, or a bare language such as `en` (see below). Selects the voice and the intro phrases. |
   | `content` | yes | The article in Markdown. Plain text is valid Markdown too. |
   | `title` | no | Read first. If the content starts with the same heading, that heading is skipped. |
   | `author`, `published_date` | no | Read as a byline ("Por … Publicado em …"), using whichever is present. |
   | `takeaways` | no | Markdown. Read after the intro, before the content, introduced by "Principais pontos." / "Key takeaways." and closed by "Agora, o artigo." / "Now, the article." |
   | `link` | no | Never read aloud; stored in the MP3's `comment` tag. |

   Options: `voice`, `input_format` (`ssml` or `markup`) and `speaking_rate`.
   - Every optional field, options included, can be sent as `""`, a whitespace-only string or `null`, and counts as not sent: options fall back to their defaults. Empty `language` or `content` still gets a `422`.
   - Unknown fields get a `422` that names them, so a typo such as `takeaway` is caught instead of silently dropped.
   - An invalid `published_date` is ignored (treated as unset) and logged, instead of failing the request. ISO datetimes such as `2026-11-15T10:30:00Z` are accepted and keep only the date.
   - **Languages and voices** (`languages.py`): `LANGUAGES` and `VOICES` copy the [Chirp 3 HD](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd) lists by hand. Update them when Google changes the page.
     - The language is checked against `LANGUAGES`, ignoring case. Unsupported languages are rejected (422 from the API, an error from the CLI).
     - A bare language picks a locale: the only one if there's just one (`pt` → `pt-BR`), otherwise the entry in `DEFAULT_LOCALES` (`en` → `en-US`, `es` → `es-ES`, `fr` → `fr-FR`, `nl` → `nl-NL`).
2. **Markdown to blocks** (`markdown.py`, using `markdown-it-py`)
   - Read aloud: headings (levels 1–6), paragraphs, list items (one block per item; ordered items keep their number), blockquotes, and inline code and emphasis as plain text.
   - Links: the link text is read and the URL never is. Autolinks (`<https://…>`) and bare URLs are removed entirely.
   - Tables: read row by row (header first), cells left to right separated by commas, with a short pause after each row. Empty cells are skipped.
     - Tables with 15 or more data rows or 7 or more columns are skipped entirely.
     - The limits are `MAX_TABLE_ROWS` and `MAX_TABLE_COLUMNS` in `markdown.py`.
   - Skipped: images, fenced code and raw HTML. `---` becomes a pause.
   - Indented code blocks are turned off, so indented plain text is still read.
   - Paragraphs: a blank line ends a paragraph. A single line break also ends one if the line ends like a sentence; otherwise it's soft wrapping and the lines are joined. This way plain text with one paragraph per line still splits properly.
3. **Render and chunk** (`text.py`, `styles.py`, `sentences.py`)
   - Narration order: title → byline → takeaways (label, items, closing phrase, with pauses around the closing phrase) → content.
   - Each block is rendered using its style in **`styles.py`**. There's one entry per block kind (`h1`…`h6`, `paragraph`, `list_item`, `blockquote`, `table_row`, `title`, `byline`, …), each with:
     - `pause_before` / `pause_after`, which become `<break>`;
     - optional `rate` / `pitch` / `volume`, which become `<prosody>`, e.g. a slower, lower tone for `h1`. Prosody is off by default because Google doesn't document Chirp's valid ranges; try it with a real run.
   - SSML marks paragraphs only (`<p>`). There's no `<s>`: Chirp detects sentences itself, and every tag is billed. The date uses `<say-as>`.
   - Adjacent pauses (e.g. the end of a list followed by a heading) merge into the longest one.
   - `markup` mode approximates pauses with `[pause short]` (under 500 ms), `[pause]` (under 1 s) and `[pause long]`, and ignores prosody.
   - Blocks are packed into chunks of up to **4,500 bytes**; the API limit is 5,000. A block that's too big is split by sentence, then by word.
   - The sentence splitter (`sentences.py`) only finds safe cut points inside oversized paragraphs, so it's kept minimal.
     - It splits after `.`, `!`, `?` or `…` followed by a space, unless the next word starts lowercase or the word before is an initial (`J. R. R.`).
     - Closing quotes stay with their sentence, and CJK `。！？` are recognized.
     - There are no abbreviation lists, so a rare cut can land after "Dr.". That costs only a slightly odd pause.
   - Every chunk is a complete document, so no SSML element is ever split.
4. **Synthesize** (`tts.py`)
   - Each chunk is sent to `synthesize_speech` with MP3 encoding, up to 4 at a time. The results come back in article order.
   - Voices are named `<locale>-Chirp3-HD-<Name>`; the default is `Charon`.
5. **Join** (`audio.py`)
   - `ffmpeg -f concat -c copy` joins the parts into one MP3 without re-encoding.
   - It writes ID3 tags (title, artist, date, language, and the link as `comment`) and deletes the temporary part files.
6. **Store** (`storage.py`)
   - A `Storage` interface has two methods: `path_for` and `publish`. The file is named `<date>-<title-slug>.mp3`. Without a date the prefix is dropped; without a title it uses the first heading, then `article-<hash>`.
   - `LocalStorage` writes to `FALAE_OUTPUT_DIR` (default `./output`). `publish` returns the file path.
   - `GCSStorage` writes to a temp dir, uploads the file to the bucket as `audio/mpeg`, deletes the local copy and returns `gs://<bucket>/<file>`. The bucket defaults to `com-talleye-falae`.
   - `DropboxStorage` works the same way: it uploads to `FALAE_DROPBOX_FOLDER` and returns `dropbox:/<folder>/<file>`. An existing file with the same name is overwritten.
     - It authenticates with a **refresh token** plus the app key and secret, so it never expires. The SDK fetches short-lived access tokens itself. See [Dropbox setup](#dropbox-setup).
     - Files up to 150 MB (about 2.5 hours of audio) are sent in one request; bigger ones use an upload session.
     - The folder is created by Dropbox on the first upload. With an "App folder" app it's relative to `Apps/<app name>/`; empty means that folder itself.
   - The destination is set per instance, never per request. The API builds one storage per process from the environment:

     | Variable | Default | Notes |
     |---|---|---|
     | `FALAE_STORAGE` | `local` | `local`, `gcs` or `dropbox`. Set it in `.env`; the image has no default of its own. |
     | `FALAE_GCS_BUCKET` | `com-talleye-falae` | Used when `FALAE_STORAGE=gcs`. |
     | `FALAE_OUTPUT_DIR` | `output` | Used when `FALAE_STORAGE=local`. |
     | `FALAE_DROPBOX_FOLDER` | app folder root | Used when `FALAE_STORAGE=dropbox`, e.g. `/falae`. |
     | `FALAE_DROPBOX_APP_KEY`, `FALAE_DROPBOX_APP_SECRET`, `FALAE_DROPBOX_REFRESH_TOKEN` | — | Required when `FALAE_STORAGE=dropbox`; if any is missing the server won't start. |

### Entry points

- **`falae/api.py`** is the HTTP service. It has `POST /synthesize` and `GET /healthz`.
  - `POST /synthesize` is asynchronous: synthesis takes 30–60 seconds, so the endpoint only validates the request and returns **`202 Accepted`** with `{"status": "accepted", "location": "gs://com-talleye-falae/<file>.mp3"}`. Invalid input still gets an immediate `422`.
  - The pipeline then runs as a FastAPI background task after the response is sent. Check `location` for the file, or set a webhook (below) to be told when it's done.
  - The task is a plain `def`, so the blocking TTS and ffmpeg work runs in the threadpool.
  - Failures are logged (`synthesis failed for <file>`, with the traceback). Successes log `saved <location> …`.
- **Webhook** (`falae/webhook.py`): if `FALAE_WEBHOOK_URL` is set, each finished job `POST`s JSON to it:

  ```json
  {"storage": "gcs", "file_path": "gs://com-talleye-falae/<file>.mp3", "message": "The audio file is ready for you!"}
  ```

  - `storage` is `local`, `gcs` or `dropbox`; `file_path` is the same value as `location` in the `202` response.
  - On failure, `message` is the error message (no traceback), and `file_path` is where the file would have been.
  - Delivery is best effort: one attempt with a 10-second timeout, no retries. A failed delivery is logged (`webhook delivery failed for <file>`) and doesn't affect the job.
  - The URL must be `http` or `https`; anything else stops the server at startup. The CLI ignores it.
- **Access control** (`falae/auth.py`) applies to `POST /synthesize` only; `GET /healthz` stays open.
  - If `FALAE_API_KEY` is set, requests must send it in the `X-API-Key` header, or they get `401`. If it's unset, no key is needed and a warning is logged at startup. It's fixed per process.
  - The key is checked before the request body is validated, so a rejected caller learns nothing about the API.
- **`falae_cli.py`** runs the same pipeline from the command line, without a server. Add `--dry-run` to print the chunks without calling Google.

### Seams for testing and extension

- **`Synthesizer`** is an interface. Tests pass in a fake that returns silent MP3s, so they never call Google.
- **`Storage`** is an interface, so adding an upload destination doesn't change the rest of the pipeline. `GCSStorage` and `DropboxStorage` accept an injected client; tests pass fakes, so they never call GCS or Dropbox.

### Deployment

The service runs on a VPS with Docker Compose (see [Run with Docker Compose](#run-with-docker-compose)).

- The `Dockerfile` is based on `python:3.11-slim`, adds ffmpeg, and starts uvicorn on `$PORT`.
- **Secrets live in `.env` on the server** (`FALAE_API_KEY`, `FALAE_DROPBOX_*`) and the Google key file. Neither is copied into the image. Restrict them to your user: `chmod 600 .env /path/to/key.json`.
  - Generate the API key with `openssl rand -base64 32`. In n8n, use a **Header Auth** credential with name `X-API-Key` and the key as the value.
- **Jobs run in the background inside the process**, after the `202`. Restarting or stopping the container (`docker compose up --build`, `restart`, a reboot) loses any job in progress, and nothing retries it. If that becomes a problem, the next step is a persistent job queue.
- **Pick a storage that survives the container**: `local` writes to `./output` on the host (mounted at `/output`), `gcs` uploads to the bucket, `dropbox` uploads to Dropbox.
  - For `gcs`, the service account needs `roles/storage.objectUser` on the bucket. `objectCreator` isn't enough: re-synthesizing an article overwrites its file, which needs delete permission.
- Google authentication uses the credentials file mounted by `compose.yaml` (`GOOGLE_APPLICATION_CREDENTIALS`).

## Development setup

### Prerequisites

- **Python 3.11 or newer.**
- **ffmpeg** on your `PATH`, used to join the audio parts. On macOS: `brew install ffmpeg`. Tests that need it are skipped if it's missing.
- **Google Cloud credentials**, only for real synthesis. `--dry-run` and the tests never call Google.
  Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install), then follow [Google Cloud setup](#google-cloud-setup).

### Google Cloud setup

falae needs the Text-to-Speech API, and with `FALAE_STORAGE=gcs`, a bucket it can write to. Do this once per project. You need Owner (or equivalent) on the project, and billing must be enabled.

```sh
PROJECT_ID=your-project-id
BUCKET=your-bucket-name            # globally unique; set FALAE_GCS_BUCKET to it if it isn't com-talleye-falae
gcloud config set project "$PROJECT_ID"

# 1. Enable the APIs.
gcloud services enable texttospeech.googleapis.com storage.googleapis.com

# 2. Create the bucket (skip if it exists).
gcloud storage buckets create "gs://$BUCKET" --location=us-central1 --uniform-bucket-level-access

# 3. Create a service account for falae.
gcloud iam service-accounts create falae --display-name="falae"
SA="falae@$PROJECT_ID.iam.gserviceaccount.com"

# 4. Let it write and overwrite objects in the bucket (objectCreator can't overwrite).
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectUser
```

- **Text-to-Speech** has no per-resource permissions: a service account in a project with the API enabled can call it. If you get `PERMISSION_DENIED` from TTS, grant the service account the *Cloud Text-to-Speech API User* role on the project.

**For Docker Compose on a server, or the CLI: create a key file.**

```sh
mkdir -p ~/.config/falae
gcloud iam service-accounts keys create ~/.config/falae/key.json --iam-account="$SA"
chmod 600 ~/.config/falae/key.json
```

Then set `GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/key.json` in `.env`. The path must be absolute, with no `~`.

- A key is a long-lived password: never commit it or copy it into the image. Rotate it with `gcloud iam service-accounts keys list --iam-account="$SA"` and `keys delete`.
- If key creation fails with `constraints/iam.disableServiceAccountKeyCreation`, your organization blocks keys (the default for newer organizations). Use your own login below, or ask an org admin for an exception.

**For local development, you can use your own login instead of a key:**

```sh
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"   # bills TTS calls to this project
```

Leave `GOOGLE_APPLICATION_CREDENTIALS` empty. The CLI and uvicorn find this login automatically, and compose mounts `~/.config/gcloud/application_default_credentials.json`. Your user needs access to the bucket; project Owners already have it.

### Dropbox setup

Only needed with `FALAE_STORAGE=dropbox` (or `--storage dropbox`). Do this once.

1. In the [Dropbox App Console](https://www.dropbox.com/developers/apps), create an app with **Scoped access** and **App folder** access. falae then sees only `Apps/<app name>/`, not the rest of your Dropbox.
2. On the **Permissions** tab, tick `files.content.write` and click **Submit**. Do this before step 4: a token only carries the scopes enabled when it was issued.
3. On the **Settings** tab, copy the **App key** and **App secret**.
4. Get a refresh token. Open this URL in a browser, approve, and copy the code shown:
   ```
   https://www.dropbox.com/oauth2/authorize?client_id=APP_KEY&response_type=code&token_access_type=offline
   ```
   Then exchange the code (it's valid for a few minutes) and copy `refresh_token` from the response:
   ```sh
   curl https://api.dropboxapi.com/oauth2/token \
     -d code=CODE -d grant_type=authorization_code -u APP_KEY:APP_SECRET
   ```
5. Put the three values in `.env` as `FALAE_DROPBOX_APP_KEY`, `FALAE_DROPBOX_APP_SECRET` and `FALAE_DROPBOX_REFRESH_TOKEN`, and optionally set `FALAE_DROPBOX_FOLDER`.

- The refresh token doesn't expire, but it stops working if you revoke the app's access in your Dropbox settings or change its permissions. Treat it like a password.
- Google credentials are still needed for Text-to-Speech.

### Install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

This installs the package in editable mode, plus `pytest` and `httpx` for the tests.

### Configuration (`.env`)

```sh
cp .env.sample .env   # then fill in the values you need
```

`.env.sample` lists every setting with comments. `.env` is git- and docker-ignored. It's read by `docker compose`, by `uvicorn --env-file .env`, and by `falae_cli.py` (for credentials such as `GOOGLE_APPLICATION_CREDENTIALS` and `FALAE_DROPBOX_*`; storage is still chosen with CLI flags). Variables already set in your shell take precedence. Tests ignore `.env`.

### Run the tests

```sh
pytest
```

The tests use a fake `Synthesizer`, so they don't need credentials or network access.

### Run the CLI

```sh
./falae_cli.py --language pt-BR --content-file article.md \
  --title "Meu artigo" --author "Fulano" --date 2026-11-11 \
  --link https://example.com/artigo --takeaways-file takeaways.md
```

- Add `--dry-run` to print the chunks without calling Google.
- `--content-file -` (the default) reads the article from stdin.
- Other options: `--voice`, `--format` (`ssml` or `markup`), `--speaking-rate` and `--output-dir` (default `output`). See `./falae_cli.py --help`.
- Add `--storage gcs` to upload to GCS instead; `--bucket` picks the bucket (default `com-talleye-falae`).
- Add `--storage dropbox` to upload to Dropbox. Credentials come from `FALAE_DROPBOX_*` in `.env` or your shell; `--dropbox-folder` overrides `FALAE_DROPBOX_FOLDER`.
- The script runs with `python3` from your `PATH`, so activate the virtualenv first.

### Run the HTTP service

```sh
uvicorn falae.api:app --reload --port 8013 --env-file .env
curl localhost:8013/healthz
```

Send articles to `POST /synthesize` (add `-H 'X-API-Key: …'` if you set `FALAE_API_KEY`). MP3s are written to `FALAE_OUTPUT_DIR` (default `./output`). Start it with `FALAE_STORAGE=gcs` to upload to `com-talleye-falae` instead (or set `FALAE_GCS_BUCKET`), or with `FALAE_STORAGE=dropbox` to upload to Dropbox.

### Run with Docker Compose

```sh
cp .env.sample .env   # if you haven't yet
docker compose up --build
```

- `compose.yaml` builds the image, publishes it on `127.0.0.1:FALAE_PORT` (default `8013`), and loads `.env` into the container.
  - The port is bound to localhost only, so `curl localhost:8013` works on the machine itself, but the service isn't reachable from the internet.
  - n8n reaches it over the `n8n_default` Docker network at `http://falae:8013`.
- The file at `GOOGLE_APPLICATION_CREDENTIALS` (a host path) is mounted read-only at `/secrets/gcp.json`, and the variable is pointed there inside the container. Unset, it mounts your `gcloud auth application-default login` file. If the file doesn't exist, the container won't start. See [Google Cloud setup](#google-cloud-setup).
- With `FALAE_STORAGE=local`, MP3s are written to `./output` on the host. If `.env` doesn't set `FALAE_STORAGE`, it defaults to `local`.
- A healthcheck polls `/healthz`, and the service restarts unless stopped.

### Run in Docker

```sh
docker build -t falae .
docker run --rm -p 8013:8013 --env-file .env \
  -e PORT=8013 \
  -v /absolute/path/to/key.json:/secrets/gcp.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp.json \
  falae
```

- `--env-file .env` passes your settings in. The image itself has none, and `.env` is never copied into it.
- The `-v` and `-e` pair mounts your credentials file and overrides the host path from `.env`. Use `~/.config/gcloud/application_default_credentials.json` for your own login.
- `docker run` doesn't expand `${…}` or strip quotes in `.env`, and `FALAE_PORT` has no effect here. `compose.yaml` handles all of this for you.
