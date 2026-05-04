{
  description = "Persistent Kokoro TTS daemon for Claude Code and other clients";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = import nixpkgs {inherit system;};

        # Python override that unbreaks darwin and ships the spaCy English
        # model as a proper package so kokoro never shells out to pip/uv.
        #
        # 1. nixpkgs marks python3Packages.dlinfo broken on darwin because
        #    its upstream tests assert /usr/lib/libdl.dylib exists on disk.
        #    The library's actual code path works fine (dlinfo resolves via
        #    the dyld shared cache) — we simply skip the tests and unbreak.
        # 2. Misaki (kokoro's G2P) lazy-loads en_core_web_sm. If it can't
        #    import the model module it falls through to spaCy's downloader,
        #    which shells out to pip/uv — neither of which exist inside a
        #    pure Nix env. We fetch the official wheel and build it as a
        #    python package so `import en_core_web_sm` just works.
        kokoroPython = pkgs.python313.override {
          packageOverrides = pyFinal: pyPrev: {
            dlinfo = pyPrev.dlinfo.overridePythonAttrs (old: {
              doCheck = false;
              doInstallCheck = false;
              nativeCheckInputs = [];
              meta = old.meta // {broken = false;};
            });
            # av (PyAV) ships transitively via spacy → wandb → moviepy →
            # imageio in daemonEnv. Its post-build importsCheck imports all
            # 22 av submodules in one Python process and OOM-kills (SIGKILL
            # exit 137) on 16GB-RAM aarch64-darwin under the sandbox memory
            # limit. PyAV 16.1.0+ is recent (2026-04) and not yet cached on
            # cache.nixos.org for aarch64-darwin → forced local build.
            # Skip the post-build verification only; the build itself
            # succeeds and av is importable at runtime. Linux + x86_64 keep
            # the importsCheck.
            # `overridePythonAttrs` requires a function (old -> attrs).
            # Passing a bare attrset (the previous shape) silently no-ops:
            # the Python build wraps the call and only invokes a callable,
            # so the dontUsePythonImportsCheck flag never reaches the
            # derivation and importsCheckPhase still runs → OOM on
            # aarch64-darwin returns. Wrap in `_:` so the attrset is the
            # function's return value.
            av = pyPrev.av.overridePythonAttrs (
              _:
                pkgs.lib.optionalAttrs pkgs.stdenv.isDarwin {
                  # Two hooks must both be neutralised on aarch64-darwin
                  # under the 16 GiB sandbox: pythonImportsCheckPhase (22-
                  # submodule one-shot import → SIGKILL 137) AND
                  # pytestCheckPhase (pytest collection imports the same
                  # graph and SIGKILLs at the same point). Each hook gates
                  # on its own `dontUse…` flag — `dontUsePythonImportsCheck`
                  # for python-imports-check-hook.sh, `dontUsePytestCheck`
                  # for pytest-check-hook. Setting only one leaves the
                  # other phase live; the build still OOMs.
                  dontUsePythonImportsCheck = true;
                  dontUsePytestCheck = true;
                }
            );
            en-core-web-sm = pyFinal.buildPythonPackage {
              pname = "en_core_web_sm";
              version = "3.8.0";
              format = "wheel";
              src = pkgs.fetchurl {
                url = "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl";
                hash = "sha256-GTJCnbcn1L/z3u1rNM/AXfF3lPSlLusmz4ko98Gg+4U=";
              };
              dependencies = [pyFinal.spacy];
              doCheck = false;
              pythonImportsCheck = ["en_core_web_sm"];
            };
          };
        };

        # Full-fat env for the daemon: torch + kokoro + spaCy English model.
        daemonEnv = kokoroPython.withPackages (ps: [
          ps.kokoro
          ps.soundfile
          ps.numpy
          ps.en-core-web-sm
        ]);

        # Both binaries ship the daemon.py / client.py / markdown.py trio in
        # one store path so relative imports just work when the client runs.
        speakdSrc = pkgs.runCommand "kokoro-speakd-src" {} ''
          mkdir -p $out
          install -m644 ${./daemon.py}    $out/daemon.py
          install -m644 ${./client.py}    $out/client.py
          install -m644 ${./markdown.py}  $out/markdown.py
        '';

        kokoro-speakd = pkgs.writeShellApplication {
          name = "kokoro-speakd";
          runtimeInputs = [daemonEnv];
          text = ''
            exec python3 ${speakdSrc}/daemon.py "$@"
          '';
        };

        # Client is pure stdlib — no torch, no kokoro. Stays fast and small so
        # Claude Code hooks complete well under their timeout window.
        kokoro-speak = pkgs.writeShellApplication {
          name = "kokoro-speak";
          runtimeInputs = [pkgs.python3];
          text = ''
            exec python3 ${speakdSrc}/client.py "$@"
          '';
        };
      in {
        packages = {
          inherit kokoro-speakd kokoro-speak;
          # daemonEnv is exposed so downstream flakes can reuse the same
          # overridden Python (e.g. in a launchd module that wants to pass
          # it to ProgramArguments directly).
          inherit daemonEnv;
          default = kokoro-speakd;
        };

        apps = {
          default = {
            type = "app";
            program = "${kokoro-speakd}/bin/kokoro-speakd";
          };
          kokoro-speak = {
            type = "app";
            program = "${kokoro-speak}/bin/kokoro-speak";
          };
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [daemonEnv];
          shellHook = ''
            echo "kokoro-speakd dev shell — python3 has kokoro + en_core_web_sm"
            echo "run 'python3 daemon.py' to start the daemon manually"
          '';
        };

        checks.flake-evaluates = pkgs.runCommand "flake-evaluates" {} ''
          echo "flake evaluated ok" > $out
        '';
      }
    );
}
