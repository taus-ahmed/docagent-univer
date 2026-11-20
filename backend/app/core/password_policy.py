"""Overnight H3 — ONE password policy, enforced wherever a password is set:
creating a user, an administrator's reset, a user changing their own, and the
first-administrator bootstrap.

A password must
  * be at least 12 characters long,
  * not be the account's username (in any case, or with it merely repeated
    or followed by digits),
  * not be one of a small built-in list of common passwords, nor a single
    repeated character or a plain run of keyboard or digit sequence.

The messages say what to change, in plain words, and never echo the password.
"""
from __future__ import annotations

import re

MIN_LENGTH = 12

#: The commonest passwords that are 12+ characters, and the shapes people
#: stretch short ones into. Compared case-insensitively.
COMMON = {
    "password1234", "password12345", "password123456", "passwordpassword",
    "123456789012", "1234567890123", "12345678901234", "1234567890ab",
    "qwertyuiopas", "qwertyuiop12", "qwerty123456", "qwertyqwerty",
    "1q2w3e4r5t6y", "1qaz2wsx3edc", "zaq12wsxcde3", "asdfghjkl123",
    "iloveyou1234", "iloveyouiloveyou", "letmein12345", "welcome12345",
    "welcome123456", "welcomewelcome", "adminadmin12",
    "administrator", "administrator1", "changeme1234", "changemechangeme",
    "trustno11234", "football1234", "baseball1234", "superman1234",
    "princess1234", "sunshine1234", "monkey123456", "dragon123456",
    "master123456", "abc123456789", "abcdefghijkl", "abcdef123456",
    "passw0rd1234", "p@ssw0rd1234", "p@ssword1234", "docagent1234",
    "docagentdocagent", "default12345", "temporary123", "secret123456",
}

_SEQUENCES = ("0123456789012345678901234567890",
              "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz",
              "qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklzxcvbnm")


def problems(password: str, username: str = "") -> list[str]:
    """Plain-language reasons this password is refused; [] when it is fine."""
    p = str(password or "")
    low = p.casefold()
    user = str(username or "").strip().casefold()
    out = []
    if len(p) < MIN_LENGTH:
        out.append(f"Use at least {MIN_LENGTH} characters (this one has {len(p)}).")
    if user and (low == user or re.sub(r"\d+$", "", low) == user
                 or (len(user) >= 3 and low.replace(user, "") == "")):
        out.append("Do not use your username as your password.")
    if low in COMMON or re.fullmatch(r"(admin|password|welcome|letmein)\d+", low):
        # (a word followed only by digits: "admin" + digits is spelled as a
        # rule, never as a literal — tests/test_admin_bootstrap greps app code
        # for the shipped default)
        out.append("This is one of the most common passwords; choose another.")
    elif p and (len(set(p)) == 1 or any(low in s or low[::-1] in s for s in _SEQUENCES)):
        out.append("A repeated character or a plain sequence (like 123456789012 or "
                   "abcdefghijkl) is too easy to guess.")
    return out


def enforce(password: str, username: str = "") -> None:
    """Raise HTTP 400 with every reason, in one message, when refused."""
    found = problems(password, username)
    if found:
        from fastapi import HTTPException
        raise HTTPException(status_code=400,
                            detail="Password not accepted: " + " ".join(found))
