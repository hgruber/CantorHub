"""
ejabberd REST API client for CantorHub.

Used for user account provisioning (register, ensure_bot) and room affiliation
management (set_room_affiliation). Room creation and message sending are handled
by the slixmpp bot (ejabberd_bot management command).
"""

import base64
import logging
import re
import threading
import time

import httpx
import slixmpp
from django.conf import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_CAP = 5  # max seconds between retries


def _request(endpoint, body=None, allow_statuses=None):
    """
    POST to {EJABBERD_API_URL}/api/{endpoint} with JSON body.
    Returns parsed JSON on success, {} on empty response, None on error.
    Retries on HTTP 429 up to _MAX_RETRIES times.

    allow_statuses: set of extra HTTP status codes to treat as success
    (e.g. {409} for "already exists" responses from register).
    """
    url = f"{settings.EJABBERD_API_URL.rstrip('/')}/api/{endpoint}"
    auth = (settings.EJABBERD_BOT_JID, settings.EJABBERD_BOT_PASSWORD)
    allowed = allow_statuses or set()

    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.post(
                url,
                auth=auth,
                json=body or {},
                timeout=10,
                headers={"Host": settings.EJABBERD_HOST},
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
            return {} if result is None else result
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
            "host": settings.EJABBERD_HOST,
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

    jid = f"{localpart}@{settings.EJABBERD_HOST}"
    logger.info("ejabberd: registered user %s", jid)
    return jid


def ensure_bot():
    """
    Register the bot account (idempotent). Called at startup via ejabberd_sync --sync.
    Returns True on success or if account already exists.
    """
    localpart = settings.EJABBERD_BOT_JID.split("@")[0]
    result = _request(
        "register",
        {
            "user": localpart,
            "host": settings.EJABBERD_HOST,
            "password": settings.EJABBERD_BOT_PASSWORD,
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
            settings.EJABBERD_HOST,
        )
        return True
    logger.info(
        "ejabberd: ensured bot account %s@%s",
        localpart,
        settings.EJABBERD_HOST,
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
            "host": settings.EJABBERD_HOST,
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: unregistered user %s@%s", localpart, settings.EJABBERD_HOST)
    return True


def destroy_room(muc_jid):
    """
    Destroy a MUC room on ejabberd via POST /api/destroy_room.

    Returns True on success, False on failure.
    """
    room_localpart = muc_jid.split("@")[0]
    result = _request(
        "destroy_room",
        {
            "room": room_localpart,
            "service": settings.EJABBERD_MUC_SERVICE,
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: destroyed room %s", muc_jid)
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
            "host": settings.EJABBERD_HOST,
            "newpass": password,
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: changed password for %s@%s", localpart, settings.EJABBERD_HOST)
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
            "host": settings.EJABBERD_HOST,
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
                    "host": settings.EJABBERD_HOST,
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
                    "host": settings.EJABBERD_HOST,
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
        logger.info("ejabberd: set vCard for %s@%s", localpart, settings.EJABBERD_HOST)
    return ok


def set_room_affiliation(muc_jid, user_jid, affiliation):
    """
    Set a user's affiliation in a MUC room via REST API.
    Uses 'room' (localpart) + 'service' instead of full JID.

    Affiliations: 'owner', 'admin', 'member', 'outcast', 'none'

    Returns True on success, False on failure.
    """
    # Parse muc_jid: forum-1@conference.example.net
    room_localpart = muc_jid.split("@")[0]
    service = settings.EJABBERD_MUC_SERVICE

    # Parse user_jid: user@example.org
    user_localpart = user_jid.split("@")[0]

    result = _request(
        "set_room_affiliation",
        {
            "room": room_localpart,
            "service": service,
            "user": user_localpart,
            "host": settings.EJABBERD_HOST,
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
    room_localpart = muc_jid.split("@")[0]

    result = _request(
        "get_room_affiliations",
        {
            "room": room_localpart,
            "service": settings.EJABBERD_MUC_SERVICE,
        },
    )
    if result is None:
        return []

    # result is list of dicts: {"jid": "user@host", "affiliation": "member", "reason": "..."}
    members = []
    for item in result:
        if isinstance(item, dict):
            jid = item.get("jid", "")
            affiliation = item.get("affiliation", "none")
            if jid:
                members.append((jid, affiliation))
    return members


def change_room_option(muc_jid, option, value):
    """
    Change a MUC room option via ejabberd REST API.

    Common options: 'title' (room name), 'members_only', 'persistent', etc.

    Returns True on success, False on failure.
    """
    room_localpart = muc_jid.split("@")[0]

    result = _request(
        "change_room_option",
        {
            "room": room_localpart,
            "service": settings.EJABBERD_MUC_SERVICE,
            "option": option,
            "value": value,
        },
    )
    if result is None:
        return False
    logger.debug("ejabberd: set %s=%s for room %s", option, value, muc_jid)
    return True


def get_room_occupants(muc_jid):
    """
    Get current occupants of a MUC room via REST API.
    Returns list of (jid, nick) tuples on success, empty list on failure.
    jid is the real JID including resource (e.g. "user@host/resource").
    """
    room_localpart = muc_jid.split("@")[0]

    result = _request(
        "get_room_occupants",
        {
            "room": room_localpart,
            "service": settings.EJABBERD_MUC_SERVICE,
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


def send_invitation(muc_jid, user_jid, reason="", password=""):
    """
    Send a direct invitation to a MUC room via ejabberd REST API.

    Returns True on success, False on failure.
    """
    room_localpart = muc_jid.split("@")[0]

    result = _request(
        "send_direct_invitation",
        {
            "room": room_localpart,
            "service": settings.EJABBERD_MUC_SERVICE,
            "password": password or "",
            "reason": reason or "CantorHub Forum invitation",
            "users": [user_jid],
        },
    )
    if result is None:
        return False
    logger.info("ejabberd: invited %s to %s", user_jid, muc_jid)
    return True


def _send_muc_message_thread(muc_jid, body):
    """
    Internal function to send a message to a MUC room.
    Runs in a background thread with its own event loop.
    Configures room as persistent + non-anonymous before sending,
    so the message is preserved in room history for late-joining users.
    """
    import asyncio

    async def _send():
        bot = slixmpp.ClientXMPP(
            settings.EJABBERD_BOT_JID,
            settings.EJABBERD_BOT_PASSWORD,
            sasl_mech="PLAIN",
        )
        bot.register_plugin("xep_0045")  # MUC
        bot.register_plugin("xep_0359")  # Stanza IDs

        room_jid = muc_jid

        def on_session_start(event):
            bot.send_presence()
            bot.plugin["xep_0045"].join_muc(room_jid, "CantorBot")
            # Wait for room creation, then configure and send
            bot.schedule("configure_and_send", 2, lambda: _configure_send_disconnect(bot, room_jid, body))

        def _configure_send_disconnect(bot, room_jid, body):
            # Ensure room is persistent so history is kept for late joiners
            change_room_option(room_jid, "persistent", "true")
            change_room_option(room_jid, "anonymous", "false")
            bot.send_message(mto=room_jid, mbody=body, mtype="groupchat")
            bot.schedule("disconnect", 1, bot.disconnect)

        bot.add_event_handler("session_start", on_session_start)

        host = settings.EJABBERD_HOST
        port = settings.EJABBERD_BOT_PORT
        try:
            bot.connect((host, port))
            await bot.disconnected
            logger.info("ejabberd: sent message to MUC %s", muc_jid)
        except Exception as exc:
            logger.error("ejabberd: failed to send MUC message: %s", exc)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_send())
    finally:
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def send_muc_message(muc_jid, body):
    """
    Send a message to a MUC room using a short-lived slixmpp connection.
    This opens a connection, joins the room, sends the message, then disconnects.

    Returns True on success, False on failure.
    """
    # Run in daemon thread (non-blocking)
    thread = threading.Thread(target=_send_muc_message_thread, args=(muc_jid, body), daemon=True)
    thread.start()
    logger.info("ejabberd: started background thread to send message to %s", muc_jid)
    return True
