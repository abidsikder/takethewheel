# AI, take the wheel 😎

Joking aside (please review your code!), this is a simple, opinionated coding agent designed for personal use. It focuses on speed through simplicity, and ease of maintenance.

### Key Differentiators
* **Super YOLO mode:** It can do anything and will not ask for permission. **Always run this inside secured environments like Docker sandbox.** (you are sandboxing your agents...right?)
* **No TUI:** Exposes a plain text format that you can naturally scroll and search in your terminal.
* **Zero bloat:** Made specifically to meet my needs. Only one dependency! The only time you'll spend waiting is for HTTP calls. No catering to other edge cases or complex model setups.

Keeping things simple also means it's straightforward to fork and customize. Try changing the system prompt to match your own preferences!

## Installation

Install with `uv tool` from the public GitHub repository:

```sh
uv tool install git+https://github.com/abidsikder/takethewheel.git
```

## Usage

Gemini Flash and Pro (via OpenRouter)
```sh
takethewheel flash
```
```sh
takethewheel pro
```
Make sure an `OPENROUTER_API_KEY` is in your env.

Opus 4.7, us-east-1 (via Bedrock Mantle):
```sh
takethewheel opus
```
Make sure an `AWS_BEARER_TOKEN_BEDROCK` is in your env.

## Context via agents.md

You can automatically pass context to the agent on startup with an `agents.md` file in the directory you invoke the agent in.

To include other file contents automatically, start a line with the `@` symbol followed by the file path. For example:

```txt
@./README.md
@./important_script.py

Additional instructions...
```
