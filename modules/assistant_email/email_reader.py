import imaplib
import email
import re
import time
import os
import datetime
from email.header import decode_header
from typing import List, Dict, Any, Tuple, Optional

# Per-account isolated caches: {email_id: {"time": stamp, "data": []}}
_account_caches: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 60 # 60 seconds caching per account
_account_errors: Dict[str, Optional[str]] = {}

def invalidate_cache(email_id: Optional[str] = None):
    """Invalidates cache for a specific account or all accounts."""
    global _account_caches, _account_errors
    if email_id:
        norm = email_id.strip().lower()
        _account_caches.pop(norm, None)
        _account_errors.pop(norm, None)
    else:
        _account_caches.clear()
        _account_errors.clear()

def strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    return " ".join(clean.split())

def _decode_header_str(header_val: Any) -> str:
    if not header_val:
        return ""
    try:
        decoded_parts = decode_header(header_val)
        parts = []
        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                enc = encoding or "utf-8"
                try:
                    parts.append(content.decode(enc, errors="ignore"))
                except Exception:
                    parts.append(content.decode("latin1", errors="ignore"))
            else:
                parts.append(str(content))
        return "".join(parts).strip()
    except Exception:
        return str(header_val)

def _get_imap_connection(email_id: str, email_pass: str, imap_host: str = "imap.gmail.com", imap_port: int = 993, timeout: int = 20) -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=timeout)
    mail.login(email_id, email_pass)
    return mail

def fetch_latest_emails_with_status(
    limit: int = 5,
    email_id: Optional[str] = None,
    email_pass: Optional[str] = None,
    criterion: str = "ALL",
    search_query: Optional[str] = None,
    folder: str = "INBOX",
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
    timeout: int = 20,
    attachments_only: bool = False,
    attachment_scan_limit: int = 500
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetches emails with isolated per-account caching, guaranteed IMAP logout cleanup,
    and genuine filtering for UNSEEN, date-based queries, or custom folders.
    """
    global _account_caches, _account_errors

    if not email_id or not email_pass:
        return [], {"success": False, "error": "Email credentials not provided", "source": "none"}

    acc_key = email_id.strip().lower()

    # Check cache only for standard ALL query without custom search or date filter
    if criterion == "ALL" and not search_query and not date_from and not date_to and folder.upper() == "INBOX":
        cached = _account_caches.get(acc_key)
        last_err = _account_errors.get(acc_key)
        if cached and (time.time() - cached.get("time", 0) < CACHE_TTL) and cached.get("data") and not last_err:
            return cached["data"][:limit], {"success": True, "error": None, "source": "cache"}

    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        mail.select(folder)

        # Build search criterion
        imap_search_args = []
        if search_query:
            # Search message headers and body. Escape quotes/control characters so
            # natural-language input cannot break the IMAP SEARCH expression.
            clean_q = re.sub(r"[\r\n\x00]", " ", str(search_query))
            clean_q = clean_q.replace("\\", "\\\\").replace('"', '\\"').strip()
            quoted_q = f'"{clean_q}"'
            imap_search_args = [
                "OR", "SUBJECT", quoted_q,
                "OR", "FROM", quoted_q,
                "OR", "TO", quoted_q, "BODY", quoted_q,
            ]
        elif criterion.upper() == "UNSEEN":
            imap_search_args = ["UNSEEN"]
        elif criterion.upper() == "TODAY":
            today_str = datetime.date.today().strftime("%d-%b-%Y")
            imap_search_args = ["SINCE", f'"{today_str}"']
        elif criterion.upper() == "YESTERDAY":
            yesterday = datetime.date.today() - datetime.timedelta(days=1)
            today = datetime.date.today()
            imap_search_args = ["SINCE", f'"{yesterday.strftime("%d-%b-%Y")}"', "BEFORE", f'"{today.strftime("%d-%b-%Y")}"']
        elif criterion.upper() == "LAST_7_DAYS":
            d7 = datetime.date.today() - datetime.timedelta(days=7)
            imap_search_args = ["SINCE", f'"{d7.strftime("%d-%b-%Y")}"']
        elif criterion.upper() == "LAST_30_DAYS":
            d30 = datetime.date.today() - datetime.timedelta(days=30)
            imap_search_args = ["SINCE", f'"{d30.strftime("%d-%b-%Y")}"']
        elif date_from or date_to:
            if date_from and date_to:
                imap_search_args = ["SINCE", f'"{date_from.strftime("%d-%b-%Y")}"', "BEFORE", f'"{date_to.strftime("%d-%b-%Y")}"']
            elif date_from:
                imap_search_args = ["SINCE", f'"{date_from.strftime("%d-%b-%Y")}"']
            elif date_to:
                imap_search_args = ["BEFORE", f'"{date_to.strftime("%d-%b-%Y")}"']
        else:
            imap_search_args = ["ALL"]

        status, messages = mail.search(None, *imap_search_args)
        if status != "OK" or not messages or not messages[0]:
            # No messages found for criterion
            _account_errors[acc_key] = None
            return [], {"success": True, "error": None, "source": "live", "count": 0}

        email_ids = messages[0].split()
        fetch_limit = max(limit, 10)
        if attachments_only:
            # Attachment discovery must inspect a wider window than the default
            # latest-message view. Bound the scan to keep IMAP work predictable.
            scan_limit = max(1, min(int(attachment_scan_limit), 5000))
            selected_ids = email_ids[-scan_limit:]
        else:
            selected_ids = email_ids[-fetch_limit:]
        scanned_count = len(selected_ids)
        scan_truncated = bool(attachments_only and len(email_ids) > len(selected_ids))

        email_list = []
        for e_id in reversed(selected_ids):
            try:
                msg_status, msg_data = mail.fetch(e_id, "(RFC822)")
                if msg_status != "OK" or not msg_data:
                    continue

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = _decode_header_str(msg.get("Subject", "(No Subject)"))
                        sender = _decode_header_str(msg.get("From", "Unknown"))
                        to_header = _decode_header_str(msg.get("To", ""))
                        date_header = _decode_header_str(msg.get("Date", ""))
                        message_id = _decode_header_str(msg.get("Message-ID", ""))

                        body = ""
                        attachments_meta = []

                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                disposition = str(part.get("Content-Disposition") or "")
                                fname = part.get_filename()

                                if fname:
                                    fname_decoded = _decode_header_str(fname)
                                    attachments_meta.append({
                                        "filename": fname_decoded,
                                        "content_type": content_type
                                    })

                                if content_type == "text/plain" and "attachment" not in disposition and not body:
                                    try:
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            body = payload.decode(errors="ignore")
                                    except Exception:
                                        pass
                                elif content_type == "text/html" and not body and "attachment" not in disposition:
                                    try:
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            body = strip_html(payload.decode(errors="ignore"))
                                    except Exception:
                                        pass
                        else:
                            try:
                                payload = msg.get_payload(decode=True)
                                if payload:
                                    body = payload.decode(errors="ignore")
                            except Exception:
                                body = str(msg.get_payload() or "")

                        # Determine if message is unread
                        flags_status, flags_data = mail.fetch(e_id, "(FLAGS)")
                        is_read = True
                        if flags_status == "OK" and flags_data:
                            raw_flags = str(flags_data[0])
                            is_read = "\\Seen" in raw_flags

                        if attachments_only and not attachments_meta:
                            continue
                        email_list.append({
                            "id": e_id.decode() if isinstance(e_id, bytes) else str(e_id),
                            "subject": subject,
                            "sender": sender,
                            "to": to_header,
                            "body": strip_html(body),
                            "raw_body": body,
                            "date": date_header,
                            "message_id": message_id,
                            "is_read": is_read,
                            "attachments": attachments_meta
                        })
            except Exception as e:
                # Tolerant item fetch error
                continue

        _account_errors[acc_key] = None
        if email_list and criterion == "ALL" and not search_query and folder.upper() == "INBOX":
            _account_caches[acc_key] = {
                "time": time.time(),
                "data": email_list
            }

        return email_list[:limit], {
            "success": True,
            "error": None,
            "source": "live",
            "count": len(email_list),
            "scanned_count": scanned_count,
            "scan_truncated": scan_truncated,
            "attachments_only": attachments_only,
        }

    except Exception as e:
        err_msg = str(e)
        _account_errors[acc_key] = err_msg
        print(f"[READER ERROR] {err_msg}")

        # Check authentication error
        is_auth_error = any(k in err_msg.lower() for k in [
            "authenticationfailed", "application-specific password required",
            "invalid credentials", "login failed", "command auth failed"
        ])

        if is_auth_error:
            _account_caches[acc_key] = {"time": 0, "data": []}
            return [], {"success": False, "error": f"Authentication failed ({err_msg})", "source": "auth_failure"}

        # Safe cached fallback for network glitches
        cached = _account_caches.get(acc_key)
        if cached and cached.get("data"):
            return cached["data"][:limit], {"success": True, "error": err_msg, "source": "cached_fallback"}

        return [], {"success": False, "error": err_msg, "source": "error"}

    finally:
        if mail is not None:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

def fetch_latest_emails(limit: int = 5, email_id: Optional[str] = None, email_pass: Optional[str] = None) -> List[Dict[str, Any]]:
    emails, _ = fetch_latest_emails_with_status(limit=limit, email_id=email_id, email_pass=email_pass)
    return emails

def get_latest_email(email_id: Optional[str] = None, email_pass: Optional[str] = None) -> Optional[Dict[str, Any]]:
    emails = fetch_latest_emails(limit=1, email_id=email_id, email_pass=email_pass)
    return emails[0] if emails else None

def count_unread_emails(email_id: str, email_pass: str, timeout: int = 15) -> Tuple[int, Dict[str, Any]]:
    """Accurately counts unread messages using IMAP SEARCH UNSEEN."""
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        mail.select("INBOX")
        status, messages = mail.search(None, "UNSEEN")
        if status == "OK" and messages and messages[0]:
            count = len(messages[0].split())
            return count, {"success": True}
        return 0, {"success": True}
    except Exception as e:
        return 0, {"success": False, "error": str(e)}
    finally:
        if mail is not None:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

def organize_email_message(
    email_uid: str,
    action: str, # "mark_read", "mark_unread", "star", "unstar", "trash", "archive"
    email_id: str,
    email_pass: str,
    timeout: int = 15
) -> Dict[str, Any]:
    """Applies organization action to an email via IMAP flags or folder operations."""
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        mail.select("INBOX")

        if action == "mark_read":
            mail.store(email_uid, "+FLAGS", "(\\Seen)")
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email marked as read."}

        elif action == "mark_unread":
            mail.store(email_uid, "-FLAGS", "(\\Seen)")
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email marked as unread."}

        elif action == "star":
            mail.store(email_uid, "+FLAGS", "(\\Flagged)")
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email starred."}

        elif action == "unstar":
            mail.store(email_uid, "-FLAGS", "(\\Flagged)")
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email unstarred."}

        elif action == "trash":
            # In Gmail IMAP, moving to Trash or flagging \Deleted
            try:
                mail.copy(email_uid, "[Gmail]/Trash")
            except Exception:
                try:
                    mail.copy(email_uid, "Trash")
                except Exception:
                    pass
            mail.store(email_uid, "+FLAGS", "(\\Deleted)")
            mail.expunge()
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email moved to Trash."}

        elif action == "archive":
            # In Gmail IMAP, archiving is removing from INBOX
            mail.store(email_uid, "+FLAGS", "(\\Deleted)")
            mail.expunge()
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email archived."}

        else:
            return {"success": False, "message": f"Unknown email organization action: {action}"}

    except Exception as e:
        return {"success": False, "message": f"Failed to perform {action} on email: {e}"}
    finally:
        if mail is not None:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass


def list_mailboxes(email_id: str, email_pass: str, timeout: int = 15) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Discovers all available IMAP folders/mailboxes for the account.
    Parses flags, delimiter, and assigns normalized roles (inbox, sent, drafts, trash, spam, archive, custom).
    Works across Gmail, Outlook, Yahoo, and standard RFC3501 IMAP servers.
    """
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        status, folder_lines = mail.list()
        if status != "OK" or not folder_lines:
            return [{"name": "INBOX", "display_name": "Inbox", "role": "inbox"}], {"success": True}

        folders = []
        for raw in folder_lines:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
            # Regex to parse IMAP LIST response: (\Flags) "Delimiter" "Name"
            m = re.search(r'\((?P<flags>[^\)]*)\)\s+"?(?P<delim>[^"]+)"?\s+["\']?(?P<name>[^"\']+)["\']?$', line)
            if m:
                flags = [f.strip().lower() for f in m.group("flags").split() if f.strip()]
                name = m.group("name").strip()
            else:
                flags = []
                name = line.split()[-1].strip(' "\'')

            name_clean = name.strip('"\'')
            name_low = name_clean.lower()

            # Determine standardized role
            role = "custom"
            if "\\inbox" in flags or name_low == "inbox":
                role = "inbox"
            elif "\\sent" in flags or "sent" in name_low:
                role = "sent"
            elif "\\drafts" in flags or "draft" in name_low:
                role = "drafts"
            elif "\\trash" in flags or "trash" in name_low or "bin" in name_low or "deleted" in name_low:
                role = "trash"
            elif "\\junk" in flags or "spam" in name_low or "junk" in name_low:
                role = "spam"
            elif "\\all" in flags or "\\archive" in flags or "archive" in name_low or "all mail" in name_low:
                role = "archive"

            display_name = name_clean.split("/")[-1].replace("[Gmail]", "").strip() or name_clean
            folders.append({
                "name": name_clean,
                "display_name": display_name,
                "role": role,
                "flags": flags
            })

        return folders, {"success": True}
    except Exception as e:
        return [], {"success": False, "error": str(e)}
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def find_folder_by_role(role_or_name: str, email_id: str, email_pass: str) -> Optional[str]:
    """Finds the actual IMAP folder name matching a given role or user search query."""
    folders, meta = list_mailboxes(email_id, email_pass)
    if not meta.get("success") or not folders:
        return None

    target = role_or_name.lower().strip()

    # 1. Direct role match
    for f in folders:
        if f.get("role") == target:
            return f["name"]

    # 2. Display name or folder name match
    for f in folders:
        if target == f.get("display_name", "").lower() or target == f.get("name", "").lower():
            return f["name"]

    # 3. Substring match
    for f in folders:
        if target in f.get("display_name", "").lower() or target in f.get("name", "").lower():
            return f["name"]

    return None


def move_email_message(
    email_uid: str,
    target_folder: str,
    email_id: str,
    email_pass: str,
    source_folder: str = "INBOX",
    timeout: int = 15
) -> Dict[str, Any]:
    """
    Moves an email message between IMAP folders without assuming specific provider folder syntax.
    """
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        mail.select(source_folder)

        # Copy to destination folder
        cp_stat, _ = mail.copy(email_uid, target_folder)
        if cp_stat != "OK":
            cp_stat, _ = mail.copy(email_uid, f'"{target_folder}"')

        if cp_stat == "OK":
            mail.store(email_uid, "+FLAGS", "(\\Deleted)")
            mail.expunge()
            invalidate_cache(email_id)
            return {"success": True, "message": f"Email moved to {target_folder}."}

        return {"success": False, "message": f"Could not copy email to {target_folder}."}
    except Exception as e:
        return {"success": False, "message": f"Failed to move email: {e}"}
    finally:
        if mail is not None:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

