# Snapscore Farm

Async Snapchat send engine for Render. Sends one image per cycle to a list
of recipients. Falls back to a generated black image if `media/` is empty.

## Requirements

- Python 3.11+
- A Snapchat account with valid credentials
- A Render account (Starter plan recommended — Free sleeps after 15 min)

## Local verification (no real Snapchat account needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SC_USERNAME=dummy SC_PASSWORD=dummy SC_TARGETS=dummy SC_BACKEND=stub
export CONFIG_PATH=./config.yaml   # create a local config first

python -m app.main
```

Open `http://localhost:8080/metrics` after 30 s — `sent` must be growing.
This proves the engine, worker, backoff, and media rotation are wired.

## Deploy on Render

1. Push repo (without `config.yaml`) to GitHub.
2. Render Dashboard → **New +** → **Blueprint** → pick the repo → **Apply**.
3. Render reads `render.yaml`, builds the Dockerfile, opens the web service.

### Secret File

Dashboard → **Environment** → **Secret Files**:

- **Filename:** `config.yaml`
- **Contents:** copy `config.example.yaml` and edit credentials / targets.
- Rendered to `/etc/secrets/config.yaml`, which is what `CONFIG_PATH` points to.

Alternative (no YAML): remove `CONFIG_PATH` from env, add:

| Key | Value |
|---|---|
| `SC_USERNAME` | account username |
| `SC_PASSWORD` | account password |
| `SC_TARGETS` | `user1,user2,user3` |
| `SC_BACKEND` | `pysnap` |

## Post-deploy verification

```bash
curl https://<app>.onrender.com/health
curl https://<app>.onrender.com/metrics
```

Expected log lines on boot:

```
boot: media=1 accounts=1 targets=['aeaa977','kegwag','mm2020221'] backend=pysnap workers_per_account=2
generated fallback black image at ./media/__black__.jpg
login ok: p0_xs#w0
login ok: p0_xs#w1
http server listening on 0.0.0.0:8080
```

Metric interpretation:

- `sent` grows → images reaching all three recipients per cycle.
- `auth_fail` → bad credentials or checkpoint. Stop, verify manually.
- `rate_limited` → backoff active. Lower `workers_per_account` to 1 and raise `min_delay_ms` to 1200.

## Tuning

| Key | Default | Recommendation |
|---|---|---|
| `workers_per_account` | 2 | start at 1, raise to 3 max after stability |
| `min_delay_ms` / `max_delay_ms` | 800 / 2000 | do not go below 500 ms |
| `retry_limit` | 5 | 5 is enough; above this the account is throttled |
| `backoff_max_ms` | 60000 | healthy ceiling |
