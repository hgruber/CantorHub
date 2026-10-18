# Privacy-policy compliance tracking

The public privacy policy (`intern/templates/datenschutz.html`) makes statements the
implementation must live up to. The items below are the ones where the code does **not yet**
fully match the policy text (or where a deliberate design decision needs to be recorded so it
is not mistaken for a defect).

Items are keyed by the German **section name** of `datenschutz.html`, never by its number:
the numbering has been reshuffled before and every section carries a stable `id` (`ds-daten`,
`ds-sichtbarkeit`, `ds-speicherdauer`, …) that the policy's own cross-links use. Quote the name,
link the anchor.

Resolved items (map/geocoding proxy, audit-log cleanup) have been removed once enforced —
this file tracks only what is still open.

## Open / to record

- **„Speicherdauer": a backup mirror keeps deleted data for a year** — `sicherung --loop`
  copies the whole database to `/data/sicherung/`, and the built-in Syncthing mirrors `/data`
  to the storage devices the operator accepts (see „Backup" in `INSTALL.md`). The storage side
  runs staggered versioning for 365 days, so a member's data deleted in the portal (leaving,
  an expired audit-log entry, a removed upload) survives in older copies there for up to a
  year — on a device outside the server, possibly run by someone else. The policy says nothing
  about backups. **Action item:** add a sentence on backups and their retention to
  „Speicherdauer" (and, for a third-party device, to „Hosting und technischer Betrieb");
  recommend the encrypted mode for any device the association does not control itself. The
  wording is the operator's decision, not the code's.

- **„Erhobene Daten"/„Speicherdauer": the 90-day promise is an operator duty, not a code
  guarantee** — the *access* path is IP-free (`log_format simple` in `nginx.conf` omits
  `$remote_addr`, gunicorn runs without an access log, Django's `LOGGING` has no request
  context), but the **nginx error log does record `client: <IP>`** on every error — 404s under
  `/static/` and `/media/`, rejected `auth_request` subrequests. It goes to `/dev/stderr` and
  therefore into the container's journald stream. Until realip actually engaged this was the
  front proxy's address and thus meaningless; since then it is the visitor's real address. The
  IPs the policy describes are additionally recorded one hop earlier by the haproxy in front
  (`log-format … from:%ci`), whose output goes to the host's syslog/journald. **Action item:**
  confirm that rotation actually discards entries after at most 90 days — and note this is
  now **two** places, the haproxy log *and* the container's journald stream
  (`journalctl --disk-usage`, `MaxRetentionSec`/`MaxFileSec` in `journald.conf`). The
  sentence in „Erhobene Daten" (repeated in „Hosting und technischer Betrieb" and
  „Speicherdauer") is only true as long as both rotate, and this codebase cannot enforce
  either. The „Erhobene Daten" wording was adjusted to name the reverse proxy as the
  processing component instead of implying the portal itself logs — with the error log in mind
  that wording is now slightly *under*-inclusive and should be re-read at the next policy
  revision.

- **„Erhobene Daten": forum read markers are new per-member data** — `ForumGelesen` records,
  per member and forum, up to which message the member has read (see „Unread markers" in
  `forum.md`). It is visible to no other member and serves only the member's own unread
  markers; rows go with the member (`on_delete=CASCADE`). It is usage data the policy does not
  name explicitly yet — re-read „Erhobene Daten" at the next policy revision and add a sentence
  if the wording doesn't already cover data needed to operate the portal's functions.

- **„Auftritts-Mailingliste": stored consent IPs from before the realip fix are the proxy's,
  not the subscriber's** — until `set_real_ip_from` took effect, `_client_ip()` returned the
  address of the front proxy for every request, so `Auftrittsabo.bestaetigt_ip` holds one and
  the same internal address for all rows confirmed in that period. **The dividing line is the
  deploy, not the commit:** `nginx.conf` is baked into the image (`COPY` in the `Dockerfile`,
  unlike the bind-mounted application code), so the lines added in commit 96c4239 stayed inert
  until the image was rebuilt and the container restarted on **2026-08-02**. Rows confirmed
  between that commit and that rebuild carry the proxy address too. Verified after the rebuild:
  an nginx error line reported the real public client address, so confirmations from 2026-08-02
  onwards record the subscriber. No personal data was exposed (the
  opposite: less was collected than the policy announces), but those rows carry **no**
  evidentiary value under Art. 7(1) — `bestaetigt_am` plus the `einwilligungstext` snapshot
  are all that stands behind them. Decided to leave the values in place rather than null them.
  New confirmations record the real address. See "What Django assumes about the proxy" in `architecture.md`.

- **„Zwecke und Rechtsgrundlagen": legal basis lit. b vs. lit. f for forum/chat** — membership
  admin and event organisation on Art. 6(1)(b) is fine, but forum + XMPP chat are hard to
  justify as "necessary for performance of the membership contract"; they are better grounded
  on Art. 6(1)(f) (legitimate interest in internal communication).

- **„Zwecke und Rechtsgrundlagen": implied photo consent "by uploading"** — consent for
  avatar/profile text is taken as the act of uploading. Art. 7 wants an informed, documented,
  unambiguous action; a conscious checkbox at upload time with a logged timestamp would be
  cleaner.

- **„Sichtbarkeit Deiner Daten im Portal": privacy not by default (Art. 25(2))** — by default
  all members see every other member's address, birthday and phone numbers; hiding is opt-out
  via `private_fields`. Privacy-by-default would mean at least birthday/address hidden by
  default (changing the default of `User.private_fields` + a data migration for existing rows).
  **The CardDAV export sharpens this considerably**: the same defect used to mean "the
  address is visible in the portal", it now means "the address sits in the contact database of
  every member's phone", from where the OS syncs it to Google/iCloud and messenger apps read
  it. That is the strongest argument yet for flipping the default. Two things soften it but do
  not remove it: the export honours `private_fields` **without the admin bonus**
  (`carddav.daten.carddav_sichtbar`, deliberately unlike `User.field_visible_to`), and it is
  off until `CARDDAV_AKTIV` is switched on. A third now weakens the CardDAV half of the argument
  further: `User.adressbuch_verborgen` is a full self-service opt-out from the address book, so
  the objection no longer needs the board. It does not settle the point — opt-out remains
  opt-out, and the portal itself is untouched by it.

- **„Synchronisation mit Adressbuch und Kalender": residual copies on member devices** —
  Art. 17 is satisfiable server-side (deleting a member removes their card, and the next sync
  deletes it on every device), but a card the user has meanwhile copied into a Google/iCloud
  account is out of reach. The policy informs about this (in that subsection and in „Weitergabe
  an Dritte"); whether informing is enough should be re-read at the next policy revision.
  Reinforcing it in the leave/deactivation confirmation would be the same action item already
  recorded for „Speicherdauer" below. `adressbuch_verborgen` takes the same server-side route —
  the card disappears from the collection, the CTag moves, the device deletes it — and runs into
  the same limit at a card already copied into a Google/iCloud account.

- **„Synchronisation mit Adressbuch und Kalender": the address-book opt-out does not cover the
  birthday calendar** — `adressbuch_verborgen` filters `carddav.daten.mitglieder_qs()` only.
  Someone who withdraws from the address book but leaves `geburtstag` visible still appears in
  the CalDAV birthday collection with name and full date of birth. That is a deliberate split
  (one switch per collection, each with its own established rule) and the policy says so in as
  many words in „Synchronisation mit Adressbuch und Kalender" — but it is the kind of split a
  member can misread, so re-read it at the next policy revision and consider whether one
  device-level opt-out would serve people better.

- **„Synchronisation mit Adressbuch und Kalender": the portal password ends up on private
  devices** — CardDAV and CalDAV authenticate with HTTP Basic against the *normal* portal
  password, so it is stored in the Android AccountManager or the iOS keychain. A lost, unlocked
  phone therefore grants access to the whole portal — including administrative rights if it
  belongs to a board member. This was an explicit decision, recorded here rather than treated
  as a defect. The remedy would be a revocable, per-device app password;
  `dav.auth._pruefe_anmeldung()` is deliberately the single verification point **for both
  services** so such a path can be added there without touching the views.

- **„Synchronisation mit Adressbuch und Kalender": the birthday calendar exports a date of
  birth to devices** — the CalDAV birthday collection carries name and full date of birth
  (including the year, so devices can show the age) of every active member who has not hidden
  `geburtstag`. It follows `private_fields` with no admin bonus, exactly like the vCard `BDAY`
  it duplicates, and the whole collection can be switched off with `CALDAV_GEBURTSTAGE`. It
  nevertheless widens the privacy-by-default problem above by one more field on one more device
  class — same argument, same remedy.

- **„Synchronisation mit Adressbuch und Kalender": DAV verification cache in `cache_table`** —
  a deliberate deviation from "passwords exist only as a PBKDF2 hash": for up to
  `<PREFIX>_AUTH_TTL` (default 300 s) the database holds an HMAC-SHA256 over
  username+password, keyed by `SECRET_KEY`. Without the key (an environment variable, not
  stored in the DB) the entry is worthless; with both key and database an attacker could test
  candidate passwords using fast SHA-256. The reason is cost: PBKDF2 per request is ~600 ms,
  and a sync client sends several requests every few minutes — measured 620 ms cold versus
  10 ms warm. Revocation is unaffected: a password change or `is_active=False` takes effect on
  the very next request, because the stored password hash and the active flag are re-checked on
  every cache hit.

- **„Speicherdauer": ex-member anonymisation is deliberately opt-out** (not a defect) — after a
  member leaves, forum posts keep the full real name by default; deletion **and** the milder
  placeholder anonymisation are both offered on request (Art. 17 / Art. 21). This is a
  conscious design decision, not an oversight: the membership wants the real name retained
  by default for the historical/archival integrity of the discussion record. It rests on
  Art. 6 Abs. 1 lit. f (legitimate interest in continuity and attributability of the
  communication history); the balancing test holds because only first/last name is kept,
  the portal is closed (not public), members are informed in advance via „Speicherdauer", and
  the opt-out (deletion or anonymisation) is unconditional and low-friction. The "majority
  wants it" is *not* itself the legal basis — lit. f + the easy opt-out is. **Action item:**
  reinforce this by actively pointing it out again at departure (e.g. in the leave/
  deactivation confirmation), turning the silent default into an informed, documented
  choice; until that exists the position relies on the „Speicherdauer" text alone.

- **„Auftritts-Mailingliste": open operational points (to record)** — the flow itself is
  compliant (double opt-in with a POST-only confirmation so link scanners cannot manufacture
  a consent, IP/timestamp/consent-wording snapshot per Art. 7(1), unconfirmed rows deleted
  after `MAILINGLISTE_OPTIN_TAGE`, unsubscribe deletes the row rather than flagging it, and
  the unsubscribe link is welded into `send_mailingliste_mail()` so it survives an emptied
  config text). What is *not* covered: (a) **no bounce handling** — a dead address keeps
  receiving mail forever, since nothing reads the return path; (b) `MAIL_FOOTER` is global and
  says "bitte nicht antworten", which is awkward for a public list where replying is the
  natural reaction — the `mailto:` in `List-Unsubscribe` is the only inbound path; (c)
  deliverability rests on SPF/DKIM/DMARC of the sending domain, which is host-side and not
  this codebase's job. None of these break the policy text, but (a) is the one that will
  bite first as the list grows.

- **File versions outlive the visible file (to record)** — overwriting an upload no longer
  destroys the previous revision: `DateiVersion` keeps its blob so the change reaches every
  folder the file is linked into and can be undone (see "Files as links" in `files.md`). Two consequences to keep in mind: content a member replaced on purpose
  remains restorable by anyone with write access to the file, and it survives in storage
  until pruned. **Profile pictures are exempt** since `intern/avatar_access.py`: only the
  member themselves or a holder of `intern.change_user` may overwrite, rename, move, delete
  or restore an avatar (see "Avatars are write-protected against other members" in
  `files.md`). Their version list stays *visible* to every member, though — a deliberate
  decision; if that is ever reconsidered, `datei_view` already computes the flag
  (`darf_wiederherstellen`) that would gate it. An erasure request is covered — `dateiablage.datei_loeschen` drops all versions with
  the last occurrence of a file — but the *automatic* pruning is weaker than the command's
  defaults suggest: `cleanup_dateiversionen` defaults to 10 revisions / 2 years, yet
  `start.sh` runs it as `--keep 25 --days 36500`, which disables the age rule so the
  legacy avatar history (2012 ff.) survives. **In production, superseded file revisions are
  therefore kept indefinitely** and only fall out once 25 newer ones exist. Two open points:
  (a) the policy's „Speicherdauer" section names no retention period for file versions at all
  — if members upload personal data it should say one, next to the 3-year audit-log figure;
  (b) if a real period is introduced, the imported avatar versions need exempting first,
  otherwise a blanket `--days` deletes them. See "Retention: what the cleanup jobs actually
  delete" in `files.md`.
