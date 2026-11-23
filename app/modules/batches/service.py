from time import perf_counter

from app.modules.holds import store as hold_store
from app.pipeline import process

from .seal import manifest
from .storage import write


def preserve(root, material, hold_root=None):
    started = perf_counter()
    holds = hold_store.load(hold_root) if hold_root else None
    results = process(material, holds=holds)
    return write(root, manifest(material, results, started))
