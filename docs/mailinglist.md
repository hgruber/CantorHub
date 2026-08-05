# Auftritts-Mailingliste (public gig reminders)

A public, membership-independent mailing list: visitors sign up at `/auftritte/` and are
reminded before each public gig. The triggering events are `Termin.objects.filter(
repertoire=True)` — exactly the ones `home()` already shows publicly; no model change on
`Termin`. Linked from the homepage in `#concerts` (`.concert-cta`) and as a third
`.contact-card` in `#contact`.

**Layers:** domain logic in `intern/mailingliste.py` (tokens, URLs, due-date arithmetic,
placeholders, sending), views in `intern/views/auftritte.py`, the daemon in
`intern/management/commands/send_auftritt_erinnerungen.py`. The time-dependent functions take
`jetzt` as an argument and never call the clock themselves — that is what makes `--now` and the
unit tests in `intern/tests.py` possible. The DB half is isolated in thin wrappers
(`lese_abmelde_token()` vs. `read_abmelde_token()`) so the logic stays testable without a
database.

**Double opt-in.** `auftritte_anmeldung` does `get_or_create` and always renders the *same*
status page, whether the address was new, unconfirmed or already subscribed — anything else
would be an address oracle (same reasoning as `register()`). Only the mail differs. Two brakes:
an IP throttle via `cache` and the DB-backed cooldown on `optin_gesendet_am`
(`OPTIN_COOLDOWN_MIN`), which is the one that actually stops mail-bombing a foreign address. A
honeypot field `webseite` (off-screen via `.hp-feld`, **not** `type="hidden"`) short-circuits to
the success page.

**Confirmation and unsubscribe are POST-only** — GET renders a page with a button. Outlook
SafeLinks and virus scanners fetch links ahead of the human and would otherwise document a
consent nobody gave. Unsubscribing **deletes** the row (a stored address without consent is
itself a processing operation); an unknown token renders a friendly page with status 200,
because that is the normal second click.

**Due dates.** `faelligkeit()` = event time minus N weeks, i.e. automatically the same weekday
and hour; `MAILINGLISTE_VERSANDZEIT` is only a fallback for events with no time of day (00:00).
`faellige_erinnerungen()` fires within `faellig <= jetzt <= faellig + KULANZ_STUNDEN` (24 h), so
a long outage does not produce absurdly late mail. Everything is naive local wall-clock time
(`USE_TZ = False`).

**Idempotence.** `ErinnerungVersand.get_or_create()` runs **before** sending and its
`UniqueConstraint(termin, wochen)` is the only guard against parallel processes (daemon + manual
call + a test system on the same DB); there is no process lock and deliberately no
`transaction.atomic()` around the batch — the marker must be visible to others immediately, and
SMTP has no business inside an open transaction. Side effect worth keeping: whoever subscribes
after a reminder was due does not get it retro-fitted. Known gap: a crash mid-batch leaves the
marker standing and the remaining recipients unserved — recover with `--termin <id> --force`.

**The unsubscribe token is signed, not stored.** `make_abmelde_token()` signs
`<pk>-<fingerprint>` with a plain `Signer` (no timestamp — the link sits in every mail and must
stay valid forever). The fingerprint is a short SHA-256 of the address and is **not optional**:
primary keys get reused after a delete (SQLite hands out `max(rowid)+1` without AUTOINCREMENT),
so without it an old link from a long-sent mail could unsubscribe a *different* person who later
inherited that pk. The address itself deliberately stays out of the URL — it would otherwise
land in server logs, referrers and browser history.

**The unsubscribe link cannot be configured away.** `send_mailingliste_mail()` welds it into the
`List-Unsubscribe` header, appends it to the plain-text part *above* the `-- ` signature
separator, and `emails/mailingliste.html` renders it structurally in the HTML part. Emptying
`MAIL_MAILINGLISTE_ERINNERUNG` does not remove it. `List-Unsubscribe-Post` is deliberately
**not** set: providers then send an unauthenticated POST that the CSRF middleware rejects.

**No `{beschreibung}` placeholder** — see `configuration.md`; `mail_markup` substitutes before
parsing, so a multi-line `Termin.lang` could smuggle a `{button:…:URL}` into a mail to the
general public.

Without `VEREINS_URL` or `EMAIL_HOST` the daemon **warns and writes no marker** rather than
sending — a mail with a relative, i.e. dead, unsubscribe link is not defensible. Both are re-read
every iteration, so fixing the config takes effect without restarting the loop.

Privacy-policy coverage is the „Auftritts-Mailingliste" section of `datenschutz.html` — the
only section that is not about members; open operational points (no bounce
handling) are recorded in `datenschutz.md`.

**Models.** `Auftrittsabo` is a subscriber, **not** a member — no FK to `User`. It carries the
Art. 7(1) evidence: `bestaetigt_am`, `bestaetigt_ip` and a snapshot of the consent wording. It
deliberately has **no** `bestaetigt` flag (`bestaetigt` is a property over `bestaetigt_am`;
filter with `bestaetigt_am__isnull`), no sign-up IP and no stored unsubscribe token.
`ErinnerungVersand` is one marker per `(termin, wochen)`.
