try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version('bazis-uploadable')
except PackageNotFoundError:
    __version__ = 'dev'
