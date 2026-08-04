"""
ejabberd REST API client for CantorHub.

Used for user account provisioning (register, ensure_bot), room affiliation
management (set_room_affiliation), and room option configuration
(change_room_option / configure_room). If change_room_option encounters a
400 "Room not found" error, the room is created via create_room() and
re-configured with standard options before retrying. Message sending is
handled by the slixmpp bot (ejabberd_bot management command).
"""

import base64
import hashlib
import ipaddress
import logging
import re
import time

import httpx

from intern.app_settings import get_config, get_config_int

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_CAP = 5  # max seconds between retries

_insecure_url_warned = False


class EjabberdRoomNotFoundError(Exception):
    """Raised by _request when ejabberd responds 400 'Room not found'."""


def _is_safe_host(host: str) -> bool:
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _warn_if_insecure(url):
    """Einmalige Warnung, wenn Klartext-Passwörter über das Netz gehen würden."""
    global _insecure_url_warned
    if _insecure_url_warned:
        return
    if url.startswith("https://"):
        return
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if _is_safe_host(host):
        return
    _insecure_url_warned = True
    logger.warning(
        "EJABBERD_API_URL %s ist weder lokal noch HTTPS — Passwörter werden "
        "im Klartext übertragen.",
        url,
    )


def _request(endpoint, body=None, allow_statuses=None, *, raise_on_room_not_found=False):
    """
    POST to {EJABBERD_API_URL}/api/{endpoint} with JSON body.
    Returns parsed JSON on success, {} on empty response, None on error.
    Retries on HTTP 429 up to _MAX_RETRIES times.

    allow_statuses: set of extra HTTP status codes to treat as success
    (e.g. {409} for "already exists" responses from register).
    """
    url = f"{get_config('EJABBERD_API_URL', 'http://127.0.0.1:5280').rstrip('/')}/api/{endpoint}"
    _warn_if_insecure(url)
    auth = (get_config("EJABBERD_BOT_JID", ""), get_config("EJABBERD_BOT_PASSWORD", ""))
    allowed = allow_statuses or set()

    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.post(
                url,
                auth=auth,
                json=body or {},
                timeout=get_config_int("EJABBERD_API_TIMEOUT", 10),
                headers={"Host": get_config("EJABBERD_HOST", "")},
            )
        except httpx.RequestError as exc:
            logger.error("ejabberd request error %s: %s", endpoint, exc)
            return None

        if resp.status_code == 429:
            wait = min(_RETRY_CAP, 2**attempt)
            logger.warning("ejabberd 429 on %s, retrying in %ss", endpoint, wait)
            time.sleep(wait)
            continue

        if not resp.is_success and resp.status_code not in allowed:
            if raise_on_room_not_found and resp.status_code == 400 and "Room not found" in resp.text:
                raise EjabberdRoomNotFoundError()
            logger.error(
                "ejabberd %s -> %s %s", endpoint, resp.status_code, resp.text[:200]
            )
            return None

        # ejabberd returns JSON null for commands with no result
        # Normalize to {} for consistent handling
        if not resp.content:
            return {}

        try:
            result = resp.json()
            if result is None:
                return {}
            # ejabberd returns a plain string (HTTP 200) for certain errors,
            # e.g. "Unknown host passed in 'service'" when a parameter is wrong.
            if isinstance(result, str):
                logger.error("ejabberd %s -> error: %s", endpoint, result)
                return None
            return result
        except Exception:
            return {}

    logger.error("ejabberd: gave up after %d retries on %s", _MAX_RETRIES, endpoint)
    return None


def localpart_from_username(username):
    """
    Derive a valid XMPP localpart from a Django username.
    Lowercase + replace characters outside [a-z0-9._-] with '.' + strip dots.
    """
    lp = username.lower()
    lp = re.sub(r"[^a-z0-9._\-]", ".", lp)
    return lp.strip(".")


def register_user(username, password):
    """
    Register a user account on ejabberd via POST /api/register.
    Returns the full JID 'localpart@EJABBERD_HOST' on success (including if
    the account already exists). Returns None on failure.
    """
    localpart = localpart_from_username(username)
    if not localpart:
        logger.error(
            "ejabberd: cannot derive localpart from username %r", username
        )
        return None

    result = _request(
        "register",
        {
            "user": localpart,
            "host": get_config("EJABBERD_HOST", ""),
            "password": password,
        },
        allow_statuses={409},
    )
    if result is None:
        return None
    if isinstance(result, dict) and result.get("code") == 10090:
        # User already exists — treat as success
        pass
    elif isinstance(result, dict) and result.get("error") not in (None, "conflict"):
        logger.error(
            "ejabberd register error for %r: %s", username, result
        )
        return None

    jid = f"{localpart}@{get_config("EJABBERD_HOST", "")}"
    logger.info("ejabberd: registered user %s", jid)
    return jid


def ensure_bot():
    """
    Register the bot account (idempotent). Called at startup via ejabberd_admin sync.
    Returns True on success or if account already exists.
    """
    localpart = get_config("EJABBERD_BOT_JID", "").split("@")[0]
    result = _request(
        "register",
        {
            "user": localpart,
            "host": get_config("EJABBERD_HOST", ""),
            "password": get_config("EJABBERD_BOT_PASSWORD", ""),
        },
        allow_statuses={409},
    )
    if result is None:
        return False
    # Check if this is a "user already exists" error (10090)
    # This is actually a success - we just need to ensure the password matches
    if isinstance(result, dict) and result.get("code") == 10090:
        logger.info(
            "ejabberd: bot account %s@%s already exists",
            localpart,
            get_config("EJABBERD_HOST", ""),
        )
        return True
    logger.info(
        "ejabberd: ensured bot account %s@%s",
        localpart,
        get_config("EJABBERD_HOST", ""),
    )
    return True


def unregister_user(localpart):
    """
    Delete a user account on ejabberd via POST /api/unregister.

    Returns True on success, False on failure.
    """
    result = _request(
        "unregister",
        {
            "user": localpart,
            "host": get_config("EJABBERD_HOST", ""),
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: unregistered user %s@%s", localpart, get_config("EJABBERD_HOST", ""))
    return True


def _split_muc_jid(muc_jid):
    """Return (room_localpart, service) from a full MUC JID like 'room@conference.host'."""
    parts = muc_jid.split("@", 1)
    return parts[0], (parts[1] if len(parts) > 1 else get_config("EJABBERD_MUC_SERVICE", ""))


def destroy_room(muc_jid):
    """
    Destroy a MUC room on ejabberd via POST /api/destroy_room.

    Returns True on success, False on failure.
    """
    room_localpart, service = _split_muc_jid(muc_jid)
    result = _request(
        "destroy_room",
        {
            "room": room_localpart,
            "service": service,
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: destroyed room %s", muc_jid)
    return True


def create_room(muc_jid):
    """
    Create a MUC room via ejabberd REST API.

    Returns True on success, False on failure.
    """
    room_localpart, service = _split_muc_jid(muc_jid)
    result = _request(
        "create_room",
        {
            "room": room_localpart,
            "service": service,
            "host": get_config("EJABBERD_HOST", ""),
        },
    )
    if result is None:
        logger.error("ejabberd: create_room %s failed", muc_jid)
        return False
    logger.info("ejabberd: created MUC room %s", muc_jid)
    return True


def set_user_password(localpart, password):
    """
    Change a user's password on ejabberd via POST /api/change_password.

    Returns True on success, False on failure.
    """
    result = _request(
        "change_password",
        {
            "user": localpart,
            "host": get_config("EJABBERD_HOST", ""),
            "newpass": password,
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: changed password for %s@%s", localpart, get_config("EJABBERD_HOST", ""))
    return True


def set_vcard(localpart, full_name, avatar_file=None):
    """
    Set a user's vCard on ejabberd: FN (full name) and optionally PHOTO.

    avatar_file: a FilerFileField instance with an actual file.
    Returns True on success, False on failure.
    """
    ok = True

    result = _request(
        "set_vcard",
        {
            "user": localpart,
            "host": get_config("EJABBERD_HOST", ""),
            "name": "FN",
            "content": full_name,
        },
    )
    if result is None:
        ok = False

    if avatar_file:
        try:
            f = avatar_file.file
            f.open("rb")
            data = f.read()
            f.close()
            b64 = base64.b64encode(data).decode("ascii")

            mime = getattr(avatar_file, "mime_type", "") or ""
            if not mime.startswith("image/"):
                name = getattr(avatar_file, "original_filename", "") or ""
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(ext, "image/jpeg")

            result_type = _request(
                "set_vcard2",
                {
                    "user": localpart,
                    "host": get_config("EJABBERD_HOST", ""),
                    "name": "PHOTO",
                    "subname": "TYPE",
                    "content": mime,
                },
            )
            if result_type is None:
                ok = False

            result_bval = _request(
                "set_vcard2",
                {
                    "user": localpart,
                    "host": get_config("EJABBERD_HOST", ""),
                    "name": "PHOTO",
                    "subname": "BINVAL",
                    "content": b64,
                },
            )
            if result_bval is None:
                ok = False
        except Exception as exc:
            logger.error("ejabberd: failed to read avatar for vCard: %s", exc)
            ok = False

    if ok:
        logger.info("ejabberd: set vCard for %s@%s", localpart, get_config("EJABBERD_HOST", ""))
    return ok


def set_room_vcard(muc_jid, avatar_file, name=None):
    """
    Set a MUC room's vCard (and avatar) via ejabberd change_room_option "vcard".

    Builds a vcard-temp XML with PHOTO/TYPE/BINVAL and sets it on the room.
    Clients like Conversations fetch the room vCard via IQ and display the avatar.
    Note: ejabberd requires double-quoted XML namespace attributes (single quotes
    cause a 500 internal_error). vcard_xupdate is not set here because ejabberd
    rejects "external" as a string value via change_room_option; the vCard IQ
    request path works without it.

    avatar_file: a FilerFileField instance with an actual file.
    name: optional room display name to include in the vCard FN field.
    """
    if not avatar_file:
        return False
    try:
        f = avatar_file.file
        f.open("rb")
        data = f.read()
        f.close()
        b64 = base64.b64encode(data).decode("ascii")

        mime = getattr(avatar_file, "mime_type", "") or ""
        if not mime.startswith("image/"):
            orig = getattr(avatar_file, "original_filename", "") or ""
            ext = orig.rsplit(".", 1)[-1].lower() if "." in orig else ""
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(ext, "image/jpeg")
    except FileNotFoundError as exc:
        logger.warning("ejabberd: avatar file not found, skipping vCard sync: %s", exc)
        return False
    except Exception as exc:
        logger.error("ejabberd: failed to read forum image for room vCard: %s", exc)
        return False

    fn_xml = ""
    if name:
        import xml.sax.saxutils as saxutils
        fn_xml = f"<FN>{saxutils.escape(name)}</FN>"

    # ejabberd's fxml parser requires double-quoted attribute values.
    vcard_xml = (
        f'<vCard xmlns="vcard-temp">{fn_xml}'
        f"<PHOTO><TYPE>{mime}</TYPE><BINVAL>{b64}</BINVAL></PHOTO>"
        f"</vCard>"
    )

    ok = change_room_option(muc_jid, "vcard", vcard_xml)
    # XEP-0153: set vcard_xupdate to the SHA1 hash of the raw image data so
    # ejabberd includes the hash in room presence and clients fetch the avatar.
    # "external" as string fails; the hex SHA1 hash is the accepted format.
    sha1 = hashlib.sha1(data).hexdigest()
    ok &= change_room_option(muc_jid, "vcard_xupdate", sha1)
    if ok:
        logger.info("ejabberd: set room vCard/avatar for %s", muc_jid)
    return ok


def set_room_affiliation(muc_jid, user_jid, affiliation):
    """
    Set a user's affiliation in a MUC room via REST API.

    Affiliations: 'owner', 'admin', 'member', 'outcast', 'none'

    Returns True on success, False on failure.
    """
    room_localpart, service = _split_muc_jid(muc_jid)
    user_parts = user_jid.split("@", 1)
    user_localpart = user_parts[0]
    user_host = user_parts[1] if len(user_parts) > 1 else get_config("EJABBERD_HOST", "")

    result = _request(
        "set_room_affiliation",
        {
            "room": room_localpart,
            "service": service,
            "user": user_localpart,
            "host": user_host,
            "affiliation": affiliation,
        },
    )
    if result is None:
        return False
    logger.debug(
        "ejabberd: set %s affiliation for %s in %s -> %s",
        affiliation,
        user_jid,
        muc_jid,
        result,
    )
    return True


def get_room_members(muc_jid):
    """
    Get list of members in a MUC room via REST API.
    Returns list of (user_jid, affiliation) tuples on success, empty list on failure.
    """
    room_localpart, service = _split_muc_jid(muc_jid)

    result = _request(
        "get_room_affiliations",
        {
            "room": room_localpart,
            "service": service,
        },
    )
    if result is None:
        return []

    # ejabberd returns {"username": "user", "domain": "host", "affiliation": "member", "reason": "..."}
    # Some versions may return {"jid": "user@host", ...} — both formats are handled.
    members = []
    for item in result:
        if isinstance(item, dict):
            jid = item.get("jid", "")
            if not jid:
                username = item.get("username", "")
                domain = item.get("domain", "")
                if username and domain:
                    jid = f"{username}@{domain}"
            affiliation = item.get("affiliation", "none")
            if jid:
                members.append((jid, affiliation))
    return members


def change_room_option(muc_jid, option, value):
    """
    Change a MUC room option via ejabberd REST API.

    Common options: 'title' (room name), 'members_only', 'persistent', etc.
    If the room does not exist (400 "Room not found"), it is created and
    configured with standard options before the option is retried once.

    Returns True on success, False on failure.
    """
    room_localpart, service = _split_muc_jid(muc_jid)
    params = {
        "room": room_localpart,
        "service": service,
        "option": option,
        "value": value,
    }
    try:
        result = _request("change_room_option", params, raise_on_room_not_found=True)
    except EjabberdRoomNotFoundError:
        logger.warning("ejabberd: Raum %s nicht gefunden — wird neu angelegt", muc_jid)
        if not _ensure_room(muc_jid):
            return False
        result = _request("change_room_option", params)
    if result is None:
        return False
    logger.debug("ejabberd: set %s=%s for room %s", option, value, muc_jid)
    return True


# Invariant MUC room options enforced on every (re)join and sync.
# title is handled separately because it varies per forum.
# anonymous=true (semi-anonymous) is deliberate: OMEMO in a MUC technically
# requires a non-anonymous room, so semi-anonymous rooms make clients
# (Conversations, Gajim) default to unencrypted — which is required for the
# Forum<->MUC bridge to read messages. The bot still resolves real sender JIDs
# via the admin REST API (get_room_occupants), which is unaffected by anonymity.
_ROOM_OPTIONS = {
    "persistent": "true",
    "anonymous": "true",
    "public": "false",
    "members_only": "true",
    "allow_user_invites": "true",
    "lang": "de",
}


def configure_room(muc_jid, title=None):
    """
    Apply the standard CantorHub room options to a MUC room (single source of
    truth). Sets persistent, semi-anonymous, members-only, non-public, allows
    member invites, and German language. If title is given, sets the room name.

    Semi-anonymous keeps clients from defaulting to OMEMO so the bridge can read
    messages; the bot still resolves real JIDs via the admin REST API, not in the
    client. These options are enforced (overwriting manual changes) on every bot
    (re)join and on ejabberd_admin sync. Returns True if all options were set.
    """
    ok = True
    if title:
        ok &= change_room_option(muc_jid, "title", title)
    for option, value in _ROOM_OPTIONS.items():
        ok &= change_room_option(muc_jid, option, value)
    return ok


def _ensure_room(muc_jid):
    """Create a missing MUC room and apply standard options. Returns True on success."""
    if not create_room(muc_jid):
        return False
    configure_room(muc_jid)
    return True


def assign_muc_jids():
    """Assign a MUC JID to every forum that doesn't have one yet.

    Derives ``forum-{pk}@{EJABBERD_MUC_SERVICE}`` for forums with a null/empty
    ``xmpp_muc_jid``. Suppresses the forum ``post_save`` signal via the
    ``_migrating`` flag while saving. Returns the number of forums assigned.
    """
    from intern.apps import _migrating
    from intern.models import Forum

    _migrating.active = True
    try:
        forums_needing_jid = Forum.objects.filter(xmpp_muc_jid=None) | Forum.objects.filter(
            xmpp_muc_jid=""
        )
        count = 0
        for forum in forums_needing_jid:
            forum.xmpp_muc_jid = f"forum-{forum.pk}@{get_config('EJABBERD_MUC_SERVICE', '')}"
            forum.save(update_fields=["xmpp_muc_jid"])
            count += 1
            logger.info("ejabberd: assigned %s to forum #%s", forum.xmpp_muc_jid, forum.pk)
        return count
    finally:
        _migrating.active = False


def configure_all_rooms():
    """Re-apply the standard room options to every forum with a MUC JID.

    Rooms that don't exist yet on ejabberd are skipped silently (the bot
    configures them when it first joins). Returns the number of rooms configured.
    """
    from intern.models import Forum

    count = 0
    for forum in Forum.objects.exclude(xmpp_muc_jid=None).exclude(xmpp_muc_jid=""):
        if configure_room(forum.xmpp_muc_jid, forum.thema):
            count += 1
            logger.info(
                "ejabberd: configured room %s (forum #%s)", forum.xmpp_muc_jid, forum.pk
            )
    return count


def option_is_true(options, key):
    """Robustly coerce a get_room_options value to bool.

    ejabberd may return option values as the strings "true"/"false" or as JSON
    booleans depending on version; normalize both to a Python bool.
    """
    return str((options or {}).get(key, "")).strip().lower() in ("true", "1", "yes")


def get_room_occupants(muc_jid):
    """
    Get current occupants of a MUC room via REST API.
    Returns list of (jid, nick) tuples on success, empty list on failure.
    jid is the real JID including resource (e.g. "user@host/resource").
    """
    room_localpart, service = _split_muc_jid(muc_jid)

    result = _request(
        "get_room_occupants",
        {
            "room": room_localpart,
            "service": service,
        },
    )
    if result is None:
        return []

    occupants = []
    for item in result:
        if isinstance(item, dict):
            jid = item.get("jid", "")
            nick = item.get("nick", "")
            if jid and nick:
                occupants.append((jid, nick))
    return occupants


def get_room_options(muc_jid):
    """
    Get options of a MUC room via REST API.
    Returns dict {option_name: value} if room exists, None on failure (room likely doesn't exist).
    """
    room_localpart, service = _split_muc_jid(muc_jid)
    result = _request(
        "get_room_options",
        {"room": room_localpart, "service": service},
    )
    if result is None:
        return None
    # Modern ejabberd returns a flat {option_name: value} dict.
    # Older/alternative formats: {"options": [...]} or a list of
    # {"name": ..., "value": ...} objects — normalize all to a flat dict.
    if isinstance(result, dict):
        if "options" in result and isinstance(result["options"], list):
            result = result["options"]
        else:
            return result
    return {
        item["name"]: item["value"]
        for item in result
        if isinstance(item, dict) and "name" in item
    }


def send_invitation(muc_jid, user_jid, reason="", password=""):
    """
    Send a direct invitation to a MUC room via ejabberd REST API.

    Returns True on success, False on failure.
    """
    room_localpart, service = _split_muc_jid(muc_jid)

    result = _request(
        "send_direct_invitation",
        {
            "room": room_localpart,
            "service": service,
            "password": password or "",
            "reason": reason or "CantorHub Forum invitation",
            "users": [user_jid],
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: invited %s to %s", user_jid, muc_jid)
    return True


def list_registered_users():
    """
    List all registered users on the ejabberd server via REST API.
    Returns list of JIDs (localpart@host) on success, empty list on failure.
    """
    result = _request("registered_users", {"host": get_config("EJABBERD_HOST", "")})
    if result is None:
        return []
    # Result can be a list of strings (usernames/localparts) or list of dicts
    users = []
    for item in result:
        if isinstance(item, str):
            users.append(f"{item}@{get_config("EJABBERD_HOST", "")}")
        elif isinstance(item, dict):
            username = item.get("username", item.get("user", ""))
            if username:
                users.append(f"{username}@{get_config("EJABBERD_HOST", "")}")
    return users
