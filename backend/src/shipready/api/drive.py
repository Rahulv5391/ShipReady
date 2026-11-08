"""Files a person picked in Google Drive, fetched with the short-lived token the Google Picker
gave their browser (PLAN.md Section 13.8; Decision.md D-34, D-37).

The API fetches them during the request and stores them exactly as uploaded files, so the token
is used once and is never stored, queued or logged. Google Docs and Sheets are exported as PDF and
Excel; other Google formats (Slides, Forms and so on) are refused by name.
"""

import re

import httpx

from shipready.api.uploads import MAX_FILE_BYTES, XLSX

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
# Drive file IDs are letters, digits, - and _; anything else never reaches Google's URL.
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,200}")
_GOOGLE_FORMAT = "application/vnd.google-apps."
EXPORTS = {
    f"{_GOOGLE_FORMAT}document": ("application/pdf", ".pdf"),
    f"{_GOOGLE_FORMAT}spreadsheet": (XLSX, ".xlsx"),
}
TIMEOUT_S = 30.0


class DriveError(Exception):
    """A picked file could not be fetched; `status` is the API's answer to the web app."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def fetch(client: httpx.Client, token: str, file_id: str) -> tuple[str, bytes]:
    """The file's name and bytes: downloaded, or exported for a Google Doc or Sheet."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        meta = client.get(
            f"{DRIVE_FILES}/{file_id}",
            params={
                "fields": "name,mimeType,size,capabilities/canDownload",
                "supportsAllDrives": "true",
            },
            headers=headers,
        )
        _check(meta, "a picked file")
        info = meta.json()
        name, kind = str(info["name"]), str(info["mimeType"])
        if not info.get("capabilities", {}).get("canDownload", True):
            raise DriveError(422, f"{name} cannot be downloaded: its owner has turned that off")
        if kind in EXPORTS:
            target, suffix = EXPORTS[kind]
            url, params = f"{DRIVE_FILES}/{file_id}/export", {"mimeType": target}
            name = name if name.lower().endswith(suffix) else name + suffix
        elif kind.startswith(_GOOGLE_FORMAT):
            raise DriveError(
                415,
                f"{name} is a Google {kind.removeprefix(_GOOGLE_FORMAT)} file, "
                "which ShipReady cannot read",
            )
        else:
            if int(info.get("size", 0)) > MAX_FILE_BYTES:
                raise DriveError(413, _too_large(name))
            url, params = f"{DRIVE_FILES}/{file_id}", {"alt": "media", "supportsAllDrives": "true"}
        with client.stream("GET", url, params=params, headers=headers) as response:
            if response.status_code != 200:
                response.read()
            _check(response, name)
            data = bytearray()
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > MAX_FILE_BYTES:
                    raise DriveError(413, _too_large(name))
        return name, bytes(data)
    except httpx.TransportError as error:
        raise DriveError(503, "Google Drive could not be reached; try again") from error


def _check(response: httpx.Response, what: str) -> None:
    """Google's refusals as answers the web app can show. A refused token is 400, not 401: the
    person is still signed in to ShipReady, only Google's permission has to be asked again."""
    if response.status_code == 200:
        return
    if response.status_code == 401:
        raise DriveError(400, "Google Drive did not accept the permission; choose the files again")
    if response.status_code == 403 and _reason(response) == "exportSizeLimitExceeded":
        raise DriveError(
            413, f"{what} is larger than the 10 MB Google allows when converting a Doc or Sheet"
        )
    if response.status_code in (403, 404):
        raise DriveError(422, f"{what} could not be opened in Google Drive")
    if response.status_code == 429 or response.status_code >= 500:
        raise DriveError(503, "Google Drive is busy; try again in a minute")
    raise DriveError(502, f"Google Drive answered {response.status_code} for {what}")


def _reason(response: httpx.Response) -> str | None:
    try:
        return str(response.json()["error"]["errors"][0]["reason"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _too_large(name: str) -> str:
    return f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
