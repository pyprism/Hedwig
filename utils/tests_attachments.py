"""``store_attachment_content`` must reject malformed base64 rather than
silently decoding it to corrupted bytes and storing that to S3 with no error.
"""

import base64
from unittest.mock import patch

from utils.attachments import store_attachment_content


def test_malformed_base64_is_rejected_not_silently_corrupted():
    # Non-alphabet characters (spaces are not valid base64 alphabet chars);
    # the old non-strict decode would silently discard them and "succeed"
    # with wrong bytes instead of raising.
    malformed = "not valid base64!!"

    with patch("utils.attachments.get_s3_uploader") as mocked_uploader:
        file_url, storage_key, checksum, size_bytes = store_attachment_content(
            "owner-1", "note.txt", malformed
        )

    mocked_uploader.assert_not_called()
    assert (file_url, storage_key, checksum, size_bytes) == ("", "", "", 0)


def test_well_formed_base64_still_decodes_and_uploads():
    content_b64 = base64.b64encode(b"hello world").decode()

    with patch("utils.attachments.get_s3_uploader") as mocked_uploader:
        mocked_uploader.return_value.upload_file.return_value = (
            "https://s3.example.com/note.txt"
        )
        mocked_uploader.return_value._extract_file_key.return_value = "note.txt"
        file_url, storage_key, checksum, size_bytes = store_attachment_content(
            "owner-1", "note.txt", content_b64
        )

    assert file_url == "https://s3.example.com/note.txt"
    assert size_bytes == len(b"hello world")
    assert len(checksum) == 64
