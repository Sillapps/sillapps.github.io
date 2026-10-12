#!/usr/bin/env python3
"""Sends one Firebase Cloud Messaging message to a topic (FCM HTTP v1).

Shared by the push scripts of this folder (see push/README.md). The access
token comes from the environment (FCM_ACCESS_TOKEN): in GitHub Actions,
google-github-actions/auth gives one for the fcm-sender service account of
the sillapps-push Firebase project, without any key file.

Python 3.9+, standard library only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

PROJECT = "sillapps-push"
TIMEOUT = 30


class SendError(Exception):
    pass


def send(message: dict, *, token: str | None = None, dry_run: bool = False) -> str:
    """Sends [message] (the FCM v1 "message" object). Returns the message name."""
    body = json.dumps({"message": message, "validate_only": dry_run}).encode()
    token = token or os.environ.get("FCM_ACCESS_TOKEN", "")
    if not token:
        raise SendError("FCM_ACCESS_TOKEN is not set")
    req = urllib.request.Request(
        f"https://fcm.googleapis.com/v1/projects/{PROJECT}/messages:send",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r).get("name", "")
    except urllib.error.HTTPError as e:
        raise SendError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}") from e
