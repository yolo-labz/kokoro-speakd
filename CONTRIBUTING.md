# Contributing to kokoro-speakd

Thanks for your interest in contributing!

## Development setup

1. **Clone the repo:**

   ```bash
   git clone https://github.com/yolo-labz/kokoro-speakd.git
   cd kokoro-speakd
   ```

2. **Install dependencies** (requires [uv](https://docs.astral.sh/uv/)):

   ```bash
   uv sync
   ```

3. **Run lint and type checks:**

   ```bash
   uvx ruff check .
   uvx ruff format --check .
   uvx pyright
   ```

4. **Run tests:**

   ```bash
   uvx pytest tests/ -v
   ```

## Pull request workflow

1. Fork the repo and create a feature branch from `main`.
2. Make your changes with conventional commits (`feat:`, `fix:`, etc.).
3. Ensure lint, type check, and tests pass locally.
4. Open a PR against `main`.
5. Wait for CI checks to pass before requesting review.

## Code style

- Line length: 120 characters
- Formatting: `ruff format`
- Linting: `ruff check` with rules E, F, W, I, UP, B, SIM, TCH
- Type checking: `pyright` in basic mode

## Architecture notes

- The daemon (`daemon.py`) owns the model load. Never instantiate the Kokoro model elsewhere.
- The client (`client.py`) communicates via Unix socket only. No HTTP, no TCP.
- `markdown.py` is a shared utility for markdown-to-speech conversion.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
