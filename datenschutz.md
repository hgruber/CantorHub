# Privacy-policy compliance tracking

The public privacy policy (`intern/templates/datenschutz.html`) makes statements the
implementation must live up to. The items below are the ones where the code does **not yet**
fully match the policy text (or where a deliberate design decision needs to be recorded so it
is not mistaken for a defect). The §-numbers refer to the sections in `datenschutz.html`.

Resolved items (map/geocoding proxy, audit-log cleanup) have been removed once enforced —
this file tracks only what is still open.

## Open / to record

- **§2/§10 server logs: the 90-day promise is an operator duty, not a code guarantee** —
  nothing in this repository logs a client IP: `log_format simple` in `nginx.conf` omits
  `$remote_addr`, gunicorn runs without an access log, and Django's `LOGGING` has no request
  context. The IPs the policy describes are recorded one hop earlier, by the haproxy in front
  (`log-format … from:%ci`), whose output goes to the host's syslog/journald. **Action item:**
  confirm that rotation on that host actually discards entries after at most 90 days — the
  sentence in §2 (repeated in §7 and §10) is only true as long as it does, and this codebase
  cannot enforce it. The §2 wording was adjusted to name the reverse proxy as the processing
  component instead of implying the portal itself logs.

- **§15 stored consent IPs from before the realip fix are the proxy's, not the subscriber's**
  — until `set_real_ip_from` was added to `nginx.conf`, `_client_ip()` returned the address of
  the front proxy for every request, so `Auftrittsabo.bestaetigt_ip` holds one and the same
  internal address for all rows confirmed in that period. No personal data was exposed (the
  opposite: less was collected than the policy announces), but those rows carry **no**
  evidentiary value under Art. 7(1) — `bestaetigt_am` plus the `einwilligungstext` snapshot
  are all that stands behind them. Decided to leave the values in place rather than null them.
  New confirmations record the real address. See "Request flow" in `CLAUDE.md`.

- **§3 legal basis lit. b vs. lit. f for forum/chat** — membership admin and event
  organisation on Art. 6(1)(b) is fine, but forum + XMPP chat are hard to justify as
  "necessary for performance of the membership contract"; they are better grounded on
  Art. 6(1)(f) (legitimate interest in internal communication).

- **§3 implied photo consent "by uploading"** — consent for avatar/profile text is taken
  as the act of uploading. Art. 7 wants an informed, documented, unambiguous action; a
  conscious checkbox at upload time with a logged timestamp would be cleaner.

- **§5 privacy not by default (Art. 25(2))** — by default all members see every other
  member's address, birthday and phone numbers; hiding is opt-out via `private_fields`.
  Privacy-by-default would mean at least birthday/address hidden by default (changing the
  default of `User.private_fields` + a data migration for existing rows).

- **§10 ex-member anonymisation is deliberately opt-out** (not a defect) — after a member
  leaves, forum posts keep the full real name by default; deletion **and** the milder
  placeholder anonymisation are both offered on request (Art. 17 / Art. 21). This is a
  conscious design decision, not an oversight: the membership wants the real name retained
  by default for the historical/archival integrity of the discussion record. It rests on
  Art. 6 Abs. 1 lit. f (legitimate interest in continuity and attributability of the
  communication history); the balancing test holds because only first/last name is kept,
  the portal is closed (not public), members are informed in advance via §10, and the
  opt-out (deletion or anonymisation) is unconditional and low-friction. The "majority
  wants it" is *not* itself the legal basis — lit. f + the easy opt-out is. **Action item:**
  reinforce this by actively pointing it out again at departure (e.g. in the leave/
  deactivation confirmation), turning the silent default into an informed, documented
  choice; until that exists the position relies on the §10 text alone.

- **§15 Auftritts-Mailingliste — open operational points (to record)** — the flow itself is
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
  folder the file is linked into and can be undone (see "Files as links, and file versions"
  in `CLAUDE.md`). Two consequences to keep in mind: content a member replaced on purpose
  remains restorable by anyone with write access to the file, and it survives in storage
  until pruned. **Profile pictures are exempt** since `intern/avatar_access.py`: only the
  member themselves or a holder of `intern.change_user` may overwrite, rename, move, delete
  or restore an avatar (see "Avatars are write-protected against other members" in
  `CLAUDE.md`). Their version list stays *visible* to every member, though — a deliberate
  decision; if that is ever reconsidered, `datei_view` already computes the flag
  (`darf_wiederherstellen`) that would gate it. An erasure request is covered — `_datei_loeschen` drops all versions with
  the last occurrence of a file — but the *automatic* pruning is weaker than the command's
  defaults suggest: `cleanup_dateiversionen` defaults to 10 revisions / 2 years, yet
  `start.sh` runs it as `--keep 25 --days 36500`, which disables the age rule so the
  legacy avatar history (2012 ff.) survives. **In production, superseded file revisions are
  therefore kept indefinitely** and only fall out once 25 newer ones exist. Two open points:
  (a) `datenschutz.html` §10 names no retention period for file versions at all — if members
  upload personal data it should say one, next to the 3-year audit-log figure; (b) if a real
  period is introduced, the imported avatar versions need exempting first, otherwise a
  blanket `--days` deletes them. See "Retention: what the cleanup jobs actually delete" in
  `CLAUDE.md`.
