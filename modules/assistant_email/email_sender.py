import smtplib
import os
import mimetypes
import re
from email.message import EmailMessage
from typing import List, Optional, Union, Dict, Any
from .email_memory import is_valid_email, is_placeholder_email

class SendResult(dict):
    """
    Result object that behaves both as a dict and a boolean.
    `if result:` evaluates to `result["success"]`, ensuring 100% backward compatibility
    with callers expecting boolean returns or dict returns.
    """
    def __init__(self, success: bool, status: str, message: str, **kwargs):
        super().__init__(success=success, status=status, message=message, **kwargs)
        self.success = success
        self.status = status
        self.message = message

    def __bool__(self):
        return bool(self.get("success", False))

def _sanitize_header(value: str) -> str:
    """Strips carriage returns and newlines to prevent header injection."""
    if not value:
        return ""
    return re.sub(r'[\r\n]+', ' ', str(value)).strip()

def _parse_recipients(recipients: Union[str, List[str], None]) -> List[str]:
    if not recipients:
        return []
    if isinstance(recipients, str):
        # Split by comma or semicolon
        items = [r.strip() for r in re.split(r'[,;]', recipients) if r.strip()]
        return items
    return [str(r).strip() for r in recipients if str(r).strip()]

def send_email(
    to_email: Union[str, List[str]],
    subject: str,
    body: str,
    email_id: Optional[str] = None,
    email_pass: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    cc: Optional[Union[str, List[str]]] = None,
    bcc: Optional[Union[str, List[str]]] = None,
    is_html: bool = False,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 465,
    timeout: int = 25
) -> SendResult:
    """
    Sends an email using provided credentials, with strict attachment validation,
    bounded timeouts, and guaranteed SMTP resource cleanup.
    """
    if not email_id or not email_pass:
        return SendResult(
            success=False,
            status="auth_required",
            message="Email credentials missing or not configured."
        )

    # 1. Parse and validate recipient addresses
    to_list = _parse_recipients(to_email)
    if not to_list:
        return SendResult(
            success=False,
            status="error",
            message="No recipient email address specified."
        )

    for addr in to_list:
        clean_addr = addr.split("<")[-1].split(">")[0].strip() if ("<" in addr and ">" in addr) else addr
        if not is_valid_email(clean_addr):
            return SendResult(
                success=False,
                status="error",
                message=f"Invalid recipient email address format: '{addr}'."
            )
        if is_placeholder_email(clean_addr):
            return SendResult(
                success=False,
                status="unverified_recipient",
                message=f"Cannot send to placeholder or unverified email address: '{addr}'."
            )

    cc_list = _parse_recipients(cc)
    for addr in cc_list:
        clean_addr = addr.split("<")[-1].split(">")[0].strip() if ("<" in addr and ">" in addr) else addr
        if not is_valid_email(clean_addr):
            return SendResult(
                success=False,
                status="error",
                message=f"Invalid CC email address format: '{addr}'."
            )

    bcc_list = _parse_recipients(bcc)
    for addr in bcc_list:
        clean_addr = addr.split("<")[-1].split(">")[0].strip() if ("<" in addr and ">" in addr) else addr
        if not is_valid_email(clean_addr):
            return SendResult(
                success=False,
                status="error",
                message=f"Invalid BCC email address format: '{addr}'."
            )

    # 2. Strict attachment validation — fail closed if ANY attachment is missing or unreadable
    valid_attachments_data = []
    if attachments:
        for fpath in attachments:
            if not fpath:
                continue
            normalized_path = os.path.abspath(fpath)
            if not os.path.isfile(normalized_path):
                return SendResult(
                    success=False,
                    status="error",
                    message=f"Requested attachment cannot be found: '{os.path.basename(fpath)}'."
                )
            try:
                file_size = os.path.getsize(normalized_path)
                # 25 MB typical mail attachment limit
                if file_size > 25 * 1024 * 1024:
                    return SendResult(
                        success=False,
                        status="error",
                        message=f"Attachment '{os.path.basename(fpath)}' exceeds the 25MB mail size limit ({file_size // (1024*1024)}MB)."
                    )
                with open(normalized_path, 'rb') as fp:
                    content_bytes = fp.read()
                valid_attachments_data.append((normalized_path, content_bytes))
            except Exception as e:
                return SendResult(
                    success=False,
                    status="error",
                    message=f"Could not read attachment '{os.path.basename(fpath)}': {e}."
                )

    # 3. Construct email message with sanitized headers
    msg = EmailMessage()
    clean_subject = _sanitize_header(subject or "(No Subject)")
    msg['Subject'] = clean_subject
    msg['From'] = _sanitize_header(email_id)
    msg['To'] = ", ".join([_sanitize_header(a) for a in to_list])
    if cc_list:
        msg['Cc'] = ", ".join([_sanitize_header(a) for a in cc_list])
    if bcc_list:
        msg['Bcc'] = ", ".join([_sanitize_header(a) for a in bcc_list])

    if in_reply_to:
        msg['In-Reply-To'] = _sanitize_header(in_reply_to)
    if references:
        msg['References'] = _sanitize_header(references)

    if is_html:
        msg.set_content(body or "")
        msg.add_alternative(body or "", subtype='html')
    else:
        msg.set_content(body or "")

    # Add verified attachments
    for norm_path, content_bytes in valid_attachments_data:
        fname = os.path.basename(norm_path)
        ctype, encoding = mimetypes.guess_type(norm_path)
        if ctype is None or encoding is not None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)
        msg.add_attachment(
            content_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=fname
        )

    # 4. Establish an SMTP session before attempting delivery. Port fallback is
    # permitted only while connecting/authenticating, before message transmission.
    server = None
    connection_errors = []
    ports_to_try = [smtp_port]
    alt_port = 587 if smtp_port == 465 else 465
    if alt_port != smtp_port:
        ports_to_try.append(alt_port)

    try:
        for port in ports_to_try:
            candidate = None
            try:
                if port == 465:
                    candidate = smtplib.SMTP_SSL(smtp_host, port, timeout=timeout)
                else:
                    candidate = smtplib.SMTP(smtp_host, port, timeout=timeout)
                    candidate.ehlo()
                    candidate.starttls()
                    candidate.login(email_id, str(email_pass).strip().replace(" ", ""))
                server = candidate
                break
            except smtplib.SMTPAuthenticationError:
                if candidate is not None:
                    try:
                        candidate.quit()
                    except Exception:
                        pass
                return SendResult(
                    success=False,
                    status="auth_failure",
                    message="SMTP authentication failed. Please verify your email and application-specific password."
                )
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                    TimeoutError, ConnectionResetError, OSError, smtplib.SMTPException) as exc:
                connection_errors.append(exc)
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception:
                        pass

        if server is None:
            last_error = connection_errors[-1] if connection_errors else "No SMTP connection could be established"
            return SendResult(
                success=False,
                status="network_error",
                message=f"Could not establish an SMTP connection before sending: {last_error}."
            )

        # CRITICAL: call send_message exactly once. If the connection drops during
        # this operation, the server may already have accepted the message. Never
        # retry automatically on another port after transmission has started.
        try:
            refused = server.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            return SendResult(
                success=False,
                status="recipient_rejected",
                message=f"Mail server rejected recipients: {exc}."
            )
        except smtplib.SMTPDataError as exc:
            return SendResult(
                success=False,
                status="send_rejected",
                message=f"Mail server rejected the message (SMTP {getattr(exc, 'smtp_code', 'error')})."
            )
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                TimeoutError, ConnectionResetError, OSError) as exc:
            is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
            return SendResult(
                success=False,
                status="timeout_ambiguous" if is_timeout else "ambiguous",
                message=("The connection was lost while sending. The mail server may have accepted the email. "
                         "Check the Sent folder before attempting another send."),
                retry_safe=False
            )
        except Exception:
            # Once send_message has been entered, unknown failures are treated as
            # ambiguous to avoid a duplicate message on blind retry.
            return SendResult(
                success=False,
                status="ambiguous",
                message=("The send outcome could not be confirmed. The mail server may have accepted the email. "
                         "Check the Sent folder before attempting another send."),
                retry_safe=False
            )

        if refused:
            refused_addresses = list(refused.keys())
            refused_norm = {str(addr).strip().lower() for addr in refused_addresses}
            all_envelope_addresses = to_list + cc_list + bcc_list
            accepted_addresses = [addr for addr in all_envelope_addresses if addr.strip().lower() not in refused_norm]
            # send_message may have delivered to accepted recipients while refusing
            # others. A full-message retry could duplicate delivery to accepted ones.
            return SendResult(
                success=False,
                status="partial_delivery" if accepted_addresses else "recipient_rejected",
                message=(
                    f"The server accepted the message for {', '.join(accepted_addresses)} but refused "
                    f"{', '.join(str(a) for a in refused_addresses)}. Do not resend the whole message automatically."
                    if accepted_addresses else
                    f"Mail server refused all recipients: {', '.join(str(a) for a in refused_addresses)}."
                ),
                refused_recipients=refused_addresses,
                accepted_recipients=accepted_addresses,
                retry_safe=not bool(accepted_addresses)
            )

        att_summary = f" with {len(valid_attachments_data)} attachment(s)" if valid_attachments_data else ""
        return SendResult(
            success=True,
            status="success",
            message=f"Email successfully sent to {', '.join(to_list)}{att_summary}.",
            recipients=to_list,
            cc=cc_list,
            bcc=bcc_list,
            subject=clean_subject,
            attachments_count=len(valid_attachments_data)
        )
    except smtplib.SMTPAuthenticationError:
        return SendResult(
            success=False,
            status="auth_failure",
            message="SMTP authentication failed. Please verify your email and application-specific password."
        )
    except Exception as exc:
        return SendResult(
            success=False,
            status="error",
            message=f"Email could not be sent: {type(exc).__name__}."
        )
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                try:
                    server.close()
                except Exception:
                    pass
