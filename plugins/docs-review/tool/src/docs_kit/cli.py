"""docs-kit: one entry point for every docs-review command.

Usage: docs-kit <command> [args...]

  config        print the resolved configuration (docs-kit.toml + defaults)
  stale         pages whose verified facts may have changed     (docs-stale)
  stale-bundle  triage input for stale pages, and --apply       (docs-stale-bundle)
  provenance    record a page's verification provenance         (docs-provenance)
  coverage      public surface no page covers                   (docs-coverage)
  voice         style-guide voice rules                         (docs-voice)
  features      feature register vs. docs and git log           (docs-features)
  version       print the docs-kit version

Every command takes --root <repo> (default: the git toplevel of the current
directory) and --config <file> (default: <root>/docs-kit.toml).
"""
import sys

from . import __version__, bundle, coverage, features, provenance, stale, voice
from . import config as conf

COMMANDS = {
    "stale": stale.main,
    "stale-bundle": bundle.main,
    "provenance": provenance.main,
    "coverage": coverage.main,
    "voice": voice.main,
    "features": features.main,
}


def config_main(argv=None):
    root, config, flags, pos = conf.common_args(sys.argv[1:] if argv is None else argv)
    if pos:
        sys.exit(f"unknown argument: {pos[0]}")
    cfg = conf.load(root, config)
    print(f"# root: {cfg.root}")
    print(f"# config file: {cfg.path or 'none (all defaults)'}")
    print(f"# docs-kit {__version__}")
    sys.stdout.write(conf.dump(cfg.data))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "config":
        return config_main(rest)
    if cmd in ("version", "--version"):
        print(__version__)
        return 0
    if cmd not in COMMANDS:
        print(f"docs-kit: unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
        return 2
    return COMMANDS[cmd](rest)


if __name__ == "__main__":
    sys.exit(main())
