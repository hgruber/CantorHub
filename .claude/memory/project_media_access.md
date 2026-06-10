---
name: project-media-access
description: "XMPP-compatible media access: nginx auth_request gates /media/, HMAC capability URLs let XMPP clients fetch files without a portal session"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5a22a3c5-2b17-40be-bde3-356a7a745349
---

# Media Access Architecture (post-security-audit, June 2026)

## Two-tier design

**Portal sessions** — nginx `location /media/` uses `auth_request /media-auth;` which subrequests to `/intern/media-auth/` (returns 204 for authenticated users, 403 otherwise). Files served via `X-Accel-Redirect /protected-media/<path>` through an internal nginx alias. No template changes needed: existing `filer_file.url` links still work for logged-in members.

**XMPP / capability URLs** — Route `/intern/datei/<pk>/<token>/<filename>` in `intern/views/media.py`. Token is `Signer(salt="intern.datei_token").signature(str(pk))` (HMAC from SECRET_KEY). No expiry by design: old MAM history messages fetched by XMPP clients keep resolving. Security model = "anyone with the exact link" — consistent with XEP-0363; a file posted to a MUC is already disclosed to the room.

**Message rewriting** — `_forward_to_xmpp` in `forums.py` calls `rewrite_media_urls(text)` before sending to ejabberd, converting `/media/filer_public/<uuid>/<name>` links to the tokenized capability form.

## Key files

| File | Role |
|---|---|
| `intern/views/media.py` | `media_auth`, `datei_token`, `file_token`, `rewrite_media_urls` |
| `nginx.conf` | `auth_request /media-auth;`, `location /protected-media/ { internal; alias /app/media/; }` |
| `intern/urls.py` | `media-auth/`, `datei/<int:pk>/<str:token>/<path:filename>` |
| `intern/views/forums.py` | `_forward_to_xmpp` calls `rewrite_media_urls` |

## Why no expiry on tokens

ejabberd MAM (Message Archive Management) stores messages and serves them to clients catching up. If the capability URL had an expiry, any file shared more than N days ago would break for anyone opening a backlog. Since the token is derived from SECRET_KEY + file PK (not a timestamp), rotating SECRET_KEY invalidates all old links — which is intentional when security-resetting the system.

**Related:** [[migration-numbering-constraint]] (no model change needed — tokens are pure crypto, no DB)
