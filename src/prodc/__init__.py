"""prodc: product management as code."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("prodc")
except PackageNotFoundError:  # running from source without installed metadata
    __version__ = "0+unknown"
