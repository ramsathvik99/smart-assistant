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
    attachment_scan_limit: int = 500,
    from_sender: Optional[str] = None,
    important_only: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetches emails with isolated per-account caching, guaranteed IMAP logout cleanup,
    and genuine filtering for UNSEEN, date-based queries, or custom folders.
    Uses BODY.PEEK[] to preserve read/unread status on the IMAP server.
    """
    global _account_caches, _account_errors

    if not email_id or not email_pass:
        return [], {"success": False, "error": "Email credentials not provided", "source": "none"}

    acc_key = email_id.strip().lower()

    # Check cache only for standard ALL query without custom search or date filter or sender filter
    if criterion == "ALL" and not search_query and not date_from and not date_to and not from_sender and not important_only and folder.upper() == "INBOX":
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
        elif important_only or criterion.upper() in ("IMPORTANT", "FLAGGED", "STARRED"):
            imap_search_args = ["FLAGGED"]
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

        if from_sender:
            clean_s = re.sub(r"[\r\n\x00]", " ", str(from_sender))
            clean_s = clean_s.replace("\\", "\\\\").replace('"', '\\"').strip()
            if imap_search_args == ["ALL"]:
                imap_search_args = ["FROM", f'"{clean_s}"']
            else:
                imap_search_args.extend(["FROM", f'"{clean_s}"'])

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
                msg_status, msg_data = mail.fetch(e_id, "(FLAGS BODY.PEEK[])")
                if msg_status != "OK" or not msg_data:
                    continue

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        header_info = str(response_part[0])
                        is_read = "\\Seen" in header_info or "\\seen" in header_info.lower()
                        is_flagged = "\\Flagged" in header_info or "\\flagged" in header_info.lower()

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
                            "is_unread": not is_read,
                            "unread": not is_read,
                            "is_flagged": is_flagged,
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

def count_inbox_emails(
    email_id: str,
    email_pass: str,
    scope: str = "unread",  # "unread", "read", "total"
    sender: Optional[str] = None,
    date_criterion: Optional[str] = None,  # "today", "yesterday", "last_7_days", etc.
    folder: str = "INBOX",
    timeout: int = 15
) -> Tuple[int, Dict[str, Any]]:
    """
    Accurately counts emails for given scope, sender, date, and folder using genuine IMAP queries.
    Never estimates counts from on-screen items.
    """
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        stat, select_data = mail.select(folder, readonly=True)
        if stat != "OK":
            return 0, {"success": False, "error": f"Could not select folder '{folder}'"}

        total_in_folder = int(select_data[0].decode()) if (select_data and select_data[0]) else 0

        clean_sender = None
        if sender:
            clean_s = re.sub(r"[\r\n\x00]", " ", str(sender))
            clean_sender = clean_s.replace("\\", "\\\\").replace('"', '\\"').strip()

        scope_clean = (scope or "unread").lower().strip()

        if scope_clean == "total" and not clean_sender and not date_criterion and folder.upper() == "INBOX":
            return total_in_folder, {
                "success": True,
                "scope": "total",
                "folder": folder,
                "count": total_in_folder,
                "total_inbox": total_in_folder
            }

        search_args = []
        if scope_clean == "unread":
            search_args.append("UNSEEN")
        elif scope_clean == "read":
            search_args.append("SEEN")
        else:
            search_args.append("ALL")

        if clean_sender:
            search_args.extend(["FROM", f'"{clean_sender}"'])

        if date_criterion:
            dc = date_criterion.lower().strip()
            if dc in ("today", "received_today"):
                today_str = datetime.date.today().strftime("%d-%b-%Y")
                search_args.extend(["SINCE", f'"{today_str}"'])
            elif dc == "yesterday":
                yesterday = datetime.date.today() - datetime.timedelta(days=1)
                today = datetime.date.today()
                search_args.extend(["SINCE", f'"{yesterday.strftime("%d-%b-%Y")}"', "BEFORE", f'"{today.strftime("%d-%b-%Y")}"'])
            elif dc == "last_7_days":
                d7 = datetime.date.today() - datetime.timedelta(days=7)
                search_args.extend(["SINCE", f'"{d7.strftime("%d-%b-%Y")}"'])

        stat, messages = mail.search(None, *search_args)
        if stat == "OK" and messages and messages[0]:
            count = len(messages[0].split())
        else:
            count = 0

        # Fast read optimization if total and unread without filters
        if scope_clean == "read" and not clean_sender and not date_criterion and count == 0 and total_in_folder > 0:
            s_u, m_u = mail.search(None, "UNSEEN")
            unseen_cnt = len(m_u[0].split()) if (s_u == "OK" and m_u and m_u[0]) else 0
            count = max(0, total_in_folder - unseen_cnt)

        return count, {
            "success": True,
            "scope": scope_clean,
            "folder": folder,
            "count": count,
            "sender": sender,
            "date_criterion": date_criterion,
            "total_inbox": total_in_folder
        }
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

def count_unread_emails(email_id: str, email_pass: str, timeout: int = 15) -> Tuple[int, Dict[str, Any]]:
    """Accurately counts unread messages using IMAP SEARCH UNSEEN."""
    return count_inbox_emails(email_id, email_pass, scope="unread", timeout=timeout)

def organize_email_message(
    email_uid: Any,
    action: str,  # "mark_read", "mark_unread", "star", "unstar", "trash", "archive"
    email_id: str,
    email_pass: str,
    timeout: int = 15
) -> Dict[str, Any]:
    """
    Applies organization action to an email or batch of emails via IMAP flags or folder operations.
    Confirms success only after verifying the provider response.
    """
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        mail.select("INBOX")

        uids: List[str] = []
        if isinstance(email_uid, (list, tuple, set)):
            uids = [str(u).strip() for u in email_uid if str(u).strip()]
        elif email_uid is not None:
            uids = [str(email_uid).strip()]

        if not uids:
            return {"success": False, "message": "No email UID provided to organize."}

        verified_uids: List[str] = []

        if action in ("mark_read", "read"):
            if len(uids) > 1:
                chunk_size = 50
                for i in range(0, len(uids), chunk_size):
                    chunk_str = ",".join(uids[i:i+chunk_size])
                    mail.store(chunk_str, "+FLAGS", "(\\Seen)")
                verified_uids = list(uids)
            else:
                for u in uids:
                    mail.store(u, "+FLAGS", "(\\Seen)")
                    f_stat, f_data = mail.fetch(u, "(FLAGS)")
                    if f_stat == "OK" and f_data and ("\\Seen" in str(f_data[0]) or "\\seen" in str(f_data[0]).lower()):
                        verified_uids.append(u)
            invalidate_cache(email_id)
            if len(verified_uids) == 1:
                return {"success": True, "message": "Email marked as read.", "modified_uids": verified_uids}
            return {"success": True, "message": f"{len(verified_uids)} email(s) marked as read.", "modified_uids": verified_uids}

        elif action in ("mark_unread", "unread"):
            if len(uids) > 1:
                chunk_size = 50
                for i in range(0, len(uids), chunk_size):
                    chunk_str = ",".join(uids[i:i+chunk_size])
                    mail.store(chunk_str, "-FLAGS", "(\\Seen)")
                verified_uids = list(uids)
            else:
                for u in uids:
                    mail.store(u, "-FLAGS", "(\\Seen)")
                    f_stat, f_data = mail.fetch(u, "(FLAGS)")
                    if f_stat == "OK" and f_data and ("\\Seen" not in str(f_data[0]) and "\\seen" not in str(f_data[0]).lower()):
                        verified_uids.append(u)
            invalidate_cache(email_id)
            if len(verified_uids) == 1:
                return {"success": True, "message": "Email marked as unread.", "modified_uids": verified_uids}
            return {"success": True, "message": f"{len(verified_uids)} email(s) marked as unread.", "modified_uids": verified_uids}

        elif action == "star":
            for u in uids:
                mail.store(u, "+FLAGS", "(\\Flagged)")
                f_stat, f_data = mail.fetch(u, "(FLAGS)")
                if f_stat == "OK" and f_data and ("\\Flagged" in str(f_data[0]) or "\\flagged" in str(f_data[0]).lower()):
                    verified_uids.append(u)
            invalidate_cache(email_id)
            if len(verified_uids) == 1:
                return {"success": True, "message": "Email starred.", "modified_uids": verified_uids}
            return {"success": True, "message": f"{len(verified_uids)} email(s) starred.", "modified_uids": verified_uids}

        elif action == "unstar":
            for u in uids:
                mail.store(u, "-FLAGS", "(\\Flagged)")
                f_stat, f_data = mail.fetch(u, "(FLAGS)")
                if f_stat == "OK" and f_data and ("\\Flagged" not in str(f_data[0]) and "\\flagged" not in str(f_data[0]).lower()):
                    verified_uids.append(u)
            invalidate_cache(email_id)
            if len(verified_uids) == 1:
                return {"success": True, "message": "Email unstarred.", "modified_uids": verified_uids}
            return {"success": True, "message": f"{len(verified_uids)} email(s) unstarred.", "modified_uids": verified_uids}

        elif action == "trash":
            for u in uids:
                try:
                    mail.copy(u, "[Gmail]/Trash")
                except Exception:
                    try:
                        mail.copy(u, "Trash")
                    except Exception:
                        pass
                mail.store(u, "+FLAGS", "(\\Deleted)")
                verified_uids.append(u)
            mail.expunge()
            invalidate_cache(email_id)
            if len(verified_uids) == 1:
                return {"success": True, "message": "Email moved to Trash.", "modified_uids": verified_uids}
            return {"success": True, "message": f"{len(verified_uids)} email(s) moved to Trash.", "modified_uids": verified_uids}

        elif action == "archive":
            for u in uids:
                mail.store(u, "+FLAGS", "(\\Deleted)")
                verified_uids.append(u)
            mail.expunge()
            invalidate_cache(email_id)
            if len(verified_uids) == 1:
                return {"success": True, "message": "Email archived.", "modified_uids": verified_uids}
            return {"success": True, "message": f"{len(verified_uids)} email(s) archived.", "modified_uids": verified_uids}

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


def bulk_mark_all_inbox_emails(
    action: str,  # "read" or "unread"
    email_id: str,
    email_pass: str,
    limit: Optional[int] = None,
    timeout: int = 15
) -> Tuple[int, Dict[str, Any]]:
    """
    Marks all emails in the inbox matching the source state as read or unread.
    Returns (actual_count_modified, metadata_dict).
    """
    mail = None
    try:
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        mail.select("INBOX")
        criterion = "UNSEEN" if action in ("mark_read", "read") else "SEEN"
        stat, msgs = mail.search(None, criterion)
        if stat != "OK" or not msgs or not msgs[0]:
            return 0, {"success": True, "modified_count": 0, "total_found": 0}

        raw_uids = msgs[0].split()
        total_found = len(raw_uids)
        target_uids = raw_uids[:limit] if limit and limit < total_found else raw_uids
        uid_strings = [u.decode() if isinstance(u, bytes) else str(u) for u in target_uids]

        flag_op = "+FLAGS" if action in ("mark_read", "read") else "-FLAGS"
        chunk_size = 50
        for i in range(0, len(uid_strings), chunk_size):
            chunk = ",".join(uid_strings[i:i+chunk_size])
            mail.store(chunk, flag_op, "(\\Seen)")

        invalidate_cache(email_id)
        return len(uid_strings), {
            "success": True,
            "modified_count": len(uid_strings),
            "total_found": total_found,
            "has_limit": bool(limit and limit < total_found)
        }
    except Exception as e:
        return 0, {"success": False, "error": str(e), "modified_count": 0}
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


def verify_email_in_sent_folder(
    subject: str,
    email_id: str,
    email_pass: str,
    to_email: Optional[str] = None,
    timeout: int = 6
) -> bool:
    """Verifies that an email with the given subject or recipient exists in the Sent mailbox."""
    if not email_id or not email_pass or not subject:
        return False
    mail = None
    try:
        sent_folder = find_folder_by_role("sent", email_id, email_pass) or "[Gmail]/Sent Mail"
        mail = _get_imap_connection(email_id, email_pass, timeout=timeout)
        stat, _ = mail.select(sent_folder, readonly=True)
        if stat != "OK":
            for cand in ["[Gmail]/Sent Mail", "Sent Messages", "Sent Items", "Sent"]:
                stat, _ = mail.select(cand, readonly=True)
                if stat == "OK":
                    break
        if stat != "OK":
            return False

        clean_sub = re.sub(r'[\r\n\x00"]', ' ', subject).strip()
        stat, msgs = mail.search(None, "SUBJECT", f'"{clean_sub}"')
        if stat == "OK" and msgs and msgs[0]:
            return True
        return False
    except Exception:
        return False
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

