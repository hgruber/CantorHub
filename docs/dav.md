# CardDAV and CalDAV

Two read-only DAV services that hand the member directory and the events to phones — DAVx⁵ on
Android, Contacts/Calendar on iOS. Both authenticate with the member's normal portal username
and password over HTTP Basic (**not** the portal session), both answer `405` to
`PUT`/`DELETE`/`MKCOL`/`PROPPATCH`/`LOCK`, and both are **off by default**: `CARDDAV_AKTIV`
and `CALDAV_AKTIV` are seeded as `"0"`, and while a service is off every one of its URLs
raises `Http404` — not `401`. Switching one on has privacy consequences (`datenschutz.html`,
section „Sichtbarkeit Deiner Daten im Portal"), so it deliberately requires a deliberate act.

## The shared base (`intern/dav/`)

Everything the two services have in common, and nothing else. All of it is DB-free (except the
login lookup in `auth.py`) and therefore `SimpleTestCase`-able.

| Module | Contents |
|---|---|
| `xml.py` | namespaces (`NS_DAV`/`NS_CARDDAV`/`NS_CALDAV`/`NS_CS`), `qn`, `element`, `parse_body`/`parse_propfind`/`parse_report`, `multistatus` |
| `auth.py` | `Dienst` (the per-service tuple), `dav_basic_auth(dienst)`, `dav_kopfzeilen`, the verification cache, the IP throttle |
| `http.py` | the response building blocks: `multistatus_antwort` (207), `options`, `nicht_erlaubt` (405), `aufteilen`, `privilegien`, `collection`, `href`, `supported_report`, `tiefe`, `basis`, `ressourcen_id`, `pruefe_eigentuemer` |
| `text.py` | 75-octet folding, TEXT escaping, `etag(daten, serialisierung)` / `ctag(paare)`. vCard 3.0 and iCalendar fold and escape identically, so this exists once |
| `verweise.py` | `home_sets(pk, eigener)` — the cross-advertising described below |

**Each service is a `Dienst` tuple**, and the decorator reads its config keys by prefix:
`<PREFIX>_AKTIV`, `<PREFIX>_AUTH_TTL`, `<PREFIX>_MAX_FEHLVERSUCHE_PRO_STUNDE`. That is the
whole difference between the two — plus the realm and the `DAV:` header. The decorator sets
`request.dav_user`.

**`element(ns, tag, …)`'s second parameter is `tag`, not `name`** — `name` is needed as an
*attribute*: `element(CAL, "comp", name="VEVENT")`.

**One base URL must find both services.** Three things together make that work, and all three
have to stay:

1. `/.well-known/carddav` **and** `/.well-known/caldav` (each ± slash) are registered in
   `config/urls.py`.
2. `verweise.home_sets()` puts **both** `C:addressbook-home-set` and `CAL:calendar-home-set`
   into the service root *and* the principal of **both** services. A client that only probes
   one well-known path still discovers the other collection from there — which is what makes
   DAVx⁵ create a single account holding the address book and both calendars.
3. A foreign home-set is only advertised when that service is switched on. Otherwise the
   client would be sent to a path that answers 404.

## Things that will bite when touching either service

- `@csrf_exempt` on every view. Only `GET/HEAD/OPTIONS/TRACE` are CSRF-safe, and over HTTPS
  without `Origin` *and* `Referer` — exactly what both clients send — Django answers 403.
  These are the project's only `csrf_exempt` uses.
- Never `@login_required`: `LOGIN_URL` would turn a PROPFIND into a 302 to an HTML page. DAVx⁵
  then reports "service not found", iOS fails silently.
- `GZipMiddleware` weakens a strong ETag to `W/"…"`. The single-resource responses therefore
  set `Content-Encoding: identity`, which makes the middleware bail out; the 207s carry no
  ETag header and stay compressed.
- Django's `GZipMiddleware` writes a random file name (FNAME) into the gzip header against
  BREACH. DAVx⁵ from 4.5 on decompresses with ktor, which rejects that header ("Gzip file name
  not supported") and fails account setup on the first 207. `intern.middleware.GZip` therefore
  compresses `/carddav` and `/caldav` without the name; HTML pages keep it.
- `current-user-privilege-set` containing only `<D:read/>` is what tells iOS the collection is
  read-only. Without it, opening an entry raises a save error.
- Unknown properties must be reported as a second `propstat` with 404, not omitted.
- `sync-collection` is not implemented, so it is absent from `supported-report-set` and
  `D:sync-token` is answered 404. Offering a report and then not serving it is worse than
  omitting it.
- `<pk>` in a URL must equal the authenticated member's pk, else `Http404` (the
  `views/media.py` rule — 404, never 403, so a foreign id is not confirmed by a different
  error). Integer pks rather than usernames, because `User.username` sets `validators=[]`
  ("Leerzeichen erlaubt") and hrefs must match byte-for-byte between the PROPFIND response and
  the following multiget.
- `nginx.conf` needs no change (`location /` already catches both paths, and no secret travels
  in the URL), and `requirements.txt` gains no dependency — the XML goes through
  `xml.etree.ElementTree`, with DTDs rejected outright to close Billion Laughs.
- **`_SERIALISIERUNG` must be bumped on every change to the serialisation** (`vcard.py`,
  `ical.py`) — otherwise every already-synced client keeps its old entries forever, since no
  field value changed. A changed *composition* of a collection is the CTag's job and needs no
  bump: it hashes the `(pk, etag)` pairs, so entries coming and going move it by themselves. A
  bump there would invalidate every ETag on every device and force a full re-download of all
  cards including photos, for nothing. The same reasoning covers `telefonnummern_normalisieren`
  (`INSTALL.md`): it changes the *values* of many cards, so their ETags move on their own and
  the devices reload exactly those cards once — `_SERIALISIERUNG` stays where it is.

## CardDAV address book (`intern/carddav/`)

Serves the member directory, photos included.

| URL | Purpose |
|---|---|
| `/.well-known/carddav` (± slash) | `301` → `/carddav/`; RFC 6764, the only thing iOS derives from a bare hostname. No auth |
| `/carddav` (± slash) | service root — `current-user-principal` |
| `/carddav/principal/<pk>/` | the principal |
| `/carddav/adressbuch/<pk>/` | `addressbook-home-set` |
| `/carddav/adressbuch/<pk>/mitglieder/` | the address book: `getctag`, the ETag list, both REPORTs |
| `/carddav/adressbuch/<pk>/mitglieder/<mid>.vcf` | one card |

**Three rules shape the whole design, and all of them differ from the portal:**

- **No admin bonus.** `carddav.daten.carddav_sichtbar()` consults `private_fields` and nothing
  else — unlike `User.field_visible_to()`, holders of `intern.change_user` do *not* get hidden
  fields. A vCard lands in the phone's contact database, gets backed up to Google/iCloud and is
  read by messenger apps; hiding an address is not consent to that just because the reader sits
  on the board. Consequence the architecture rests on: **every card is byte-identical for every
  reader**, so ETags are global rather than per-account.
- **Nobody gets their own card.** `mitglieder_qs()` does `exclude(pk=betrachter.pk)`; the
  `.vcf` view uses the same queryset, so the own card 404s on its direct URL too. iOS and
  Android keep their own "my card" and would treat a second copy as a duplicate. This is the
  one viewer-dependent thing about the collection, and therefore the CTag varies per member
  while the individual ETags do not.
- **A member can withhold their entire card.** `User.adressbuch_verborgen` is a self-service
  opt-out on the profile page — the stronger sibling of `private_fields`, which only hides single
  fields. It is filtered in `mitglieder_qs()`, and that one filter is enough because the
  collection, the `.vcf` URL and `getctag` all read that queryset: removing a pk changes the CTag,
  so an already-synced phone drops the card on its next PROPFIND, and the direct URL 404s. The
  checkbox only appears while `CARDDAV_AKTIV` is on, but a stored `True` survives switching the
  service off — the field is built dynamically in `UserEditForm` and is deliberately **not** in
  `Meta.fields`, or an admin saving someone else's profile would silently clear it. The birthday
  calendar is **not** covered; it still follows `private_fields["geburtstag"]` alone.

`is_active=True` applies to everyone, deliberately unlike `mitglied_list`, which shows admins
inactive members too — otherwise a board member's phone fills up with ex-members and
`geloescht_<id>` placeholders.

| Module | Contents |
|---|---|
| `vcard.py` | vCard 3.0 serialisation, pure. `kontakt_daten`, `vcard_text`, `etag`, `ctag`; folding and escaping are re-exported from `intern/dav/text.py`. Imports nothing from `intern.models` — which field a reader may see arrives as the callable `sichtbar`, so a test passes a set lookup |
| `daten.py` | the **only** DB/storage contact: `carddav_sichtbar`, `mitglieder_qs`, `foto_kennung`, `foto_bytes`, `kontakt_liste`, `ctag` |
| `views.py` | six FBVs, all `@csrf_exempt` |

**vCard 3.0, not 4.0** — iOS is most reliable with it and `PHOTO;ENCODING=b` is proven on both
platforms (the 4.0 `data:` URI is not). Folding counts **UTF-8 octets**, never splitting a
multi-byte sequence: an `ä` cut in half destroys the whole card.

**ETags never hash file bytes.** `foto_kennung()` builds `"<pk>:<sha1>:<size>"` from
`filer.File` columns — `sha1` is the content digest filer computes on upload — so a `PROPFIND
Depth:1` over the whole book costs one query and opens not a single image. `vcard.etag()`
hashes the entire `kontakt_daten` dict (sorted) rather than a hand-maintained field list, so a
field added later cannot be forgotten.

## CalDAV calendar (`intern/caldav/`)

Serves the events and, optionally, the members' birthdays.

| URL | Purpose |
|---|---|
| `/.well-known/caldav` (± slash) | `301` → `/caldav/`, no auth |
| `/caldav` (± slash) | service root |
| `/caldav/principal/<pk>/` | the principal |
| `/caldav/kalender/<pk>/` | `calendar-home-set` — Depth 1 lists both collections |
| `/caldav/kalender/<pk>/termine/` | the events: `getctag`, the ETag list, both REPORTs |
| `/caldav/kalender/<pk>/termine/<tid>.ics` | one event |
| `/caldav/kalender/<pk>/geburtstage/` `…/<mid>.ics` | the birthdays, absent when `CALDAV_GEBURTSTAGE` is off |

| Module | Contents |
|---|---|
| `ical.py` | iCalendar serialisation, pure: `termin_daten`, `geburtstag_daten`, `vcalendar_text`, `etag`, `ctag`. Imports nothing from `intern.models` and **never calls the clock** — the timezone and the `DTSTAMP` are passed in, which is what makes the tests deterministic |
| `daten.py` | the **only** DB/config contact: `eintraege(art)`, `einzeln`, `nach_zeitraum`, `ctag`, `sammlung_name`, `farbe`, `zeitzone`, `stand` |
| `views.py` | six FBVs, all `@csrf_exempt`; the two collections share `sammlung`/`eintrag` and are told apart by the `art` kwarg fixed in `urls.py` |

**Hand-rolled, not via the `icalendar` library** (which stays for the ICS feed): the ETag would
otherwise hang on a third party's byte output, and a library upgrade would trigger a full
re-sync on every device.

**Time handling.** `USE_TZ = False`, so `Termin.datum` is naive local time.

- A termin **at 00:00** with no end (or an end also at 00:00) is treated as **all-day** and
  written as `DTSTART;VALUE=DATE`. `intern/forms.py` stores `datetime.min.time()` when no time
  was entered, so 00:00 *is* the marker for "no time given". `DTEND` is **exclusive** for DATE
  values: the last day plus one, where "last day" reads `datum_bis` inclusively, exactly as the
  month grid draws it.
- Everything else is converted to **UTC** via `zoneinfo.ZoneInfo(…)`, where the zone comes from
  the `ZEITZONE` `Konfiguration` key (read by `daten.zeitzone()`, helper
  `intern.app_settings.get_zeitzone()`; fallback `settings.TIME_ZONE`). It ends in `Z`, so no
  `VTIMEZONE` is needed and no client has to guess. Without an end, the feed's two-hour
  convention applies. `settings.TIME_ZONE` is synced from `ZEITZONE` at app start
  (`apps.py ready()`), so the legacy iCal feed and Django template formatting follow the same
  zone; CalDAV reads the live value, so a config change takes effect immediately, the rest on
  the next process restart.

**Same content for everyone, so ETags are global.** There are no per-termin permissions in the
portal, and the member's own `Zusage` is deliberately **not** in the VEVENT — it would make
every ETag account-specific. Birthdays follow `private_fields` with **no admin bonus**, the
same rule as the month grid and `carddav_sichtbar`.

Of the `calendar-query` filter only the two cheap parts are honoured: a `comp-filter` asking
for `VTODO`/`VJOURNAL` gets an empty answer instead of events, and a `time-range` narrows the
list (`daten.nach_zeitraum` converts the UTC bounds back to local time first; recurring
birthdays always pass). Everything else is ignored — over-delivery is harmless in a read-only
service.

**The old ICS feed stays.** `/intern/calendar/<secret>.ics` (`ICAL_SECRET`) is deliberately
*not* replaced: Google Calendar on the web cannot subscribe to CalDAV, and the feed needs no
portal password.

**How members find the addresses.** The event and member lists used to carry three dismissible
info boxes („Termine aufs Telefon", „Kalender abonnieren", „Kontakte aufs Telefon"); on a phone
they covered the list itself and were removed in October 2026. Their job moved to the help
articles `Hilfe:Termine aufs Telefon`, `Hilfe:Kalender abonnieren` and `Hilfe:Kontakte aufs
Telefon` (`docs/articles.md`), which take the addresses from the placeholders `{CALDAV_URL}`,
`{CARDDAV_URL}`, `{ICAL_URL}`, `{WEBCAL_URL}` and `{SERVER}` and say whether the service is
switched on (`{CALDAV_STATUS}`, `{CARDDAV_STATUS}`).
