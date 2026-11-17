"""docs-kit: mechanical checks behind the docs-review skill."""
from importlib import metadata

try:
    __version__ = metadata.version("docs-kit")
except metadata.PackageNotFoundError:  # running from a source tree
    __version__ = "0+unknown"
