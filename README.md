# kokoro-speakd

Persistent [Kokoro TTS](https://github.com/hexgrad/kokoro) daemon for Claude
Code and other clients. Loads the model **once** and serves synthesis requests
over a Unix domain socket, so a machine running 10+ concurrent Claude Code
sessions doesn't pay the cold-start cost on every response.

- **Single process**, single model in RAM, regardless of how many clients.
- **Preemption over queueing** — new speech always cancels older in-flight
  playback, which is what you actually want when juggling many sessions.
- **Lazy per-language pipelines** — default English loads at startup, other
  languages spin up on first use.
- **Nix-first packaging** — `flake.nix` exports both the daemon and a
  stdlib-only client, with `dlinfo`/`en_core_web_sm` workarounds baked in
  so `python3Packages.kokoro` builds cleanly on darwin.
- **Line-delimited JSON protocol** over Unix sockets, trivial to drive from
  any shell or language.

## Quick start (with Nix)

```bash
# Start the daemon in the foreground:
nix run github:yolo-labz/kokoro-speakd

# From another terminal:
echo "hello from kokoro" | nix run github:yolo-labz/kokoro-speakd#kokoro-speak
nix run github:yolo-labz/kokoro-speakd#kokoro-speak -- ping
nix run github:yolo-labz/kokoro-speakd#kokoro-speak -- interrupt
```

The first request after a cold daemon start takes ~5–8 seconds while the
PyTorch weights warm up. Every request after that is <500 ms regardless of
how many clients are talking to the daemon.

## Claude Code hook integration (nix-darwin / home-manager)

1. Add the flake as an input:

   ```nix
   kokoro-speakd = {
     url = "github:yolo-labz/kokoro-speakd";
     inputs.nixpkgs.follows = "nixpkgs";
   };
   ```

2. Install the daemon and client on your user, and register a launchd agent
   so the daemon auto-starts at login:

   ```nix
   { inputs, pkgs, system, ... }: let
     kokoro = inputs.kokoro-speakd.packages.${system};
   in {
     home.packages = [ kokoro.kokoro-speak kokoro.kokoro-speakd ];

     launchd.agents.kokoro-speakd = {
       enable = true;
       config = {
         ProgramArguments = [ "${kokoro.kokoro-speakd}/bin/kokoro-speakd" ];
         KeepAlive = true;
         RunAtLoad = true;
         StandardOutPath = "${config.home.homeDirectory}/.cache/claude-code-tts/launchd.out.log";
         StandardErrorPath = "${config.home.homeDirectory}/.cache/claude-code-tts/launchd.err.log";
       };
     };
   }
   ```

3. Point Claude Code's `Stop`, `UserPromptSubmit`, and `SessionEnd` hooks at
   `kokoro-speak` — the daemon handles the rest. See
   [`phsb5321/NixOS`](https://github.com/phsb5321/NixOS/blob/main/modules/home/claude-code.nix)
   for a full reference integration, including the transcript walk that
   pulls Claude's final narrative text out of the JSONL log.

## Protocol

One JSON request per connection, newline-terminated. Response is a single
newline-terminated JSON object.

```json
// speak (replaces any in-flight speech)
{"action": "speak", "text": "hello there", "voice": "af_sky", "lang": "a"}
// -> {"status": "queued", "id": 42}
// -> {"status": "loading"}   // model still warming up
// -> {"status": "empty"}     // text was whitespace after stripping

// cancel current playback
{"action": "interrupt"}
// -> {"status": "ok"}

// health check
{"action": "ping"}
// -> {"status": "pong", "ready": true}
```

Defaults: `voice="af_sky"`, `lang="a"` (American English). Override per
request or globally via `KOKORO_DEFAULT_VOICE` / `KOKORO_DEFAULT_LANG`.

## Environment

**Daemon:**

- `KOKORO_SPEAKD_SOCKET` — socket path (default
  `~/.cache/claude-code-tts/kokoro-speakd.sock`)
- `KOKORO_SPEAKD_LOG` — log file path
- `KOKORO_DEFAULT_VOICE`, `KOKORO_DEFAULT_LANG` — fallback values

**Client (`kokoro-speak`):**

- `KOKORO_VOICE`, `KOKORO_LANG` — per-request overrides
- `KOKORO_MAX` — hard char cap on the text sent (default 5000)
- `KOKORO_SPEAKD_SOCKET` — matching override to reach a non-default daemon

## Voices

Kokoro ships 54 voices. American English defaults to `af_sky`; see
[hexgrad's VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)
for the full list including British English, Japanese, Mandarin, French,
Italian, and more. Set `KOKORO_VOICE=af_bella` (etc.) and reload the daemon.

## License

MIT. See [LICENSE](./LICENSE).

---

## Services

Compliance-grade AI architecture for regulated workloads — async-first, USD-denominated, LATAM-based / EN-fluent. See [blog.home301server.com.br/services](https://blog.home301server.com.br/services/).
