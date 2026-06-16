import base64
import binascii
import hashlib

from utils.s3 import get_s3_uploader


def store_attachment_content(
    owner_id, filename, content_b64, category="email-attachments"
):
    """Decode a base64 attachment payload and upload it to S3.

    Returns (file_url, storage_key, checksum_sha256, size_bytes), all empty/zero
    if the content is missing or not valid base64.
    """
    if not content_b64:
        return "", "", "", 0
    try:
        raw_bytes = base64.b64decode(content_b64)
    except (binascii.Error, ValueError):
        return "", "", "", 0
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    uploader = get_s3_uploader()
    file_url = (
        uploader.upload_file(
            raw_bytes, str(owner_id), category=category, filename=filename
        )
        or ""
    )
    storage_key = uploader._extract_file_key(file_url) if file_url else ""
    return file_url, storage_key, checksum, len(raw_bytes)
