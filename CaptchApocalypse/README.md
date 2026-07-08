# CAPTCHApocalypse — TryHackMe Walkthrough

This walk-through skips the browser-based crypto and rebuilds the whole encrypt/decrypt flow (plus CAPTCHA OCR) in a single Python script.

**Difficulty:** medium  
**Date:** 2026-07-07  
**Room:** https://tryhackme.com/room/captchapocalypse  

> [!WARNING] 
 **Authorized use only** — only ever test systems you are explicitly permitted to test. This material is intended solely for the TryHackMe CAPTCHApocalypse room on your own lab instance.

## Overview

The target is a login page sitting behind a CAPTCHA. The room specifies: *'Can you guess the password of the admin user and log in to the dashboard?'* as well as *'Use the first 100 lines of rockyou.txt'*.

<img src="images/login.jpg" alt="Login page" width="400">

After running the script and receiving the password, log in to retrieve the THM flag.


## Enumeration

From the previous rooms leading up to this challenge, it looked like this would need a headless browser to handle the encryption, but enumeration showed the crypto can be rebuilt in a script. The source ships two interesting files, `index.js` and `script.js`; the latter shows exactly how the request is assembled and encrypted:

```js
params.append("csrf_token", csrf_token);
params.append("username", username);
params.append("password", password);
params.append("captcha_input", captcha_input);
const requestData = params.toString();
const encrypted = encryptData(requestData);
```

`script.js` also leaks both RSA keys — the server public key (encrypts requests) and the client private key (decrypts replies) — which allows the exchange to be rebuilt in Python rather than driving a browser.

## Requirements

Tested on **Kali Linux** with python3.

```bash
sudo apt install tesseract-ocr python3-pil python3-pytesseract python3-pycryptodome python3-requests
```

`tesseract-ocr` is the OCR engine that `pytesseract` drives. The `python3-*` packages provide Pillow (imported as `PIL`), pytesseract, PyCryptodome (imported as `Crypto`) and Requests.

## Script Arguments

- **target IP** — start the room's machine and wait until the IP is shown.
    
- **server_pub.pem** — create this file yourself with the public key you find during enumeration:
    
    ```
    -----BEGIN PUBLIC KEY-----
    MIIB[...]
         <redacted>
    [...]DAQAB
    -----END PUBLIC KEY-----
    ```
    
- **client_priv.pem** — create this file yourself with the private key you find:
    
    ```
    -----BEGIN PRIVATE KEY-----
    MIIE[...]
         <redacted>
    [...]9+ANTmJ
    -----END PRIVATE KEY-----
    ```
    

## Usage

```bash
python3 captchApocalypse.py <target-IP> <public key> <private key>
```

Example:

```bash
python3 captchApocalypse.py 10.123.123.123 server_pub.pem client_priv.pem
```

## What you'll see

```
[*] Target   : http://10.123.123.123
[*] Username : admin
[*] Keys     : server_pub.pem (pub) / client_priv.pem (priv)
[*] Passwords: 100 (first 100 of rockyou)
[*] Captcha  : OCR, fresh per attempt (it's consumed on submit)

[  1/100] 123456                 -> Login failed!
[  2/100] 12345                  -> Login failed!
...
[+] SUCCESS  ->  admin : <the-password>
```

## Notes

Happy password hunting.
