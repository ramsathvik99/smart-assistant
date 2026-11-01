"""Download into temporary storage; extract only a verified named wheel."""
import hashlib
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(url, destination, size):
    deadline = time.monotonic() + 1800
    written = 0
    with urllib.request.urlopen(url, timeout=60) as source, Path(destination).open("wb") as target:
        while chunk := source.read(1024 * 1024):
            written += len(chunk)
            if written > size or time.monotonic() > deadline:
                raise RuntimeError("Windows ROCm archive download exceeded size/time bound")
            target.write(chunk)
    if written != size:
        raise RuntimeError("Windows ROCm archive download was truncated")


def checked_wheel(archive_path, destination, config):
    """Unrelated ZIP paths are never extracted; checks precede pip invocation."""
    if sha256(archive_path) != config["archive_sha256"]:
        raise RuntimeError("CTranslate2 archive SHA-256 mismatch")
    member = config["wheel_member"]
    member_path = PurePosixPath(member)
    if member_path.is_absolute() or ".." in member_path.parts or "\\" in member:
        raise RuntimeError("Unsafe CTranslate2 wheel member path")
    wheel_path = Path(destination) / member_path.name
    with zipfile.ZipFile(archive_path) as archive:
        members = [entry for entry in archive.infolist() if entry.filename == member]
        if len(members) != 1 or members[0].is_dir():
            raise RuntimeError("CTranslate2 archive must contain exactly one expected wheel")
        if members[0].file_size > 200 * 1024 * 1024:
            raise RuntimeError("CTranslate2 wheel exceeds extraction bound")
        with archive.open(members[0]) as source, wheel_path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
    if sha256(wheel_path) != config["wheel_sha256"]:
        wheel_path.unlink()
        raise RuntimeError("CTranslate2 wheel SHA-256 mismatch")
    return wheel_path
