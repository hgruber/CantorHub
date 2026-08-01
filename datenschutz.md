# Privacy-policy compliance tracking

The public privacy policy (`intern/templates/datenschutz.html`) makes statements the
implementation must live up to. The items below are the ones where the code does **not yet**
fully match the policy text (or where a deliberate design decision needs to be recorded so it
is not mistaken for a defect). The §-numbers refer to the sections in `datenschutz.html`.

Resolved items (map/geocoding proxy, audit-log cleanup, 90-day server-log retention) have
been removed once enforced — this file tracks only what is still open.

## Open / to record

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
