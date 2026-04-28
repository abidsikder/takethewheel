@./README.md
@./pyproject.toml
@src/takethewheel/cli.py

# Code Style
Prefer `os.environ["key"]` to `os.environ.get("key", nullish default)`. We want environment errors to crop up fast.

`except KeyboardInterrupt, EOFError` is fine as is, no need for parentheses

