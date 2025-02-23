# Cursor Account Generator

A cleaner version of [cursor-auto-free](https://github.com/chengazhen/cursor-auto-free)

## Differences
- Only bring-your-own-mailserver for now (or use Cloudflare email routing, see upstream's README)
- You need to manually click the turnstile captcha twice

## Requirements
- Cursor installed (obviously)
- Google Chrome (or any other browser compatible with zendriver)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Usage
- Copy the example configuration (`.env.example`) to `.env` and fill in your email domain and IMAP details. 

**Method 1 (easier but less reliable, generally recommended for first time users):**
In your `.env` set **USE_TEMPMAIL** to True, leave the rest of the fields empty. Then proceed to run the script.

**Method 2 (harder but more reliable):**
In your `.env` set USE_TEMPMAIL to False, and fill in the IMAP credentials of your selfhosted mailserver. You should have a postfix-regex.cf line that will force your mailserver to capture all emails to adresses that follows the pattern `EMAIL_ADDRESS_PREFIX{random_letters}@DOMAIN`. Then proceed to run the script.

- Install dependencies:

```bash
uv sync
```

- Run the script:

```bash
uv run main.py
```

## Warning

This script is not affiliated with Cursor or its developers.

This script modifies your system registry and file system in the process. Be careful.

I am not responsible for any damage you cause to your system, nor for any service issues you may face.

This script is provided for educational purposes only. 