# Cursor Account Generator

A cleaner version of [cursor-auto-free](https://github.com/chengazhen/cursor-auto-free)

## Features

- Bring your own email
- Simple execution
- Much cleaner code

## Requirements
- Cursor installed (obviously)
- Google Chrome (or any other browser compatible with zendriver)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Usage
- Copy the example configuration (`.env.example`) to `.env` and fill in your email domain and IMAP details. 
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