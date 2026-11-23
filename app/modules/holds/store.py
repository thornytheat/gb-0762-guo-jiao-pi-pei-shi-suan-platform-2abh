"""停用台账持久化：JSONL 追加写 + 文件锁 + 原子发布，重试不重复登记。"""

import fcntl
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.errors import TrialError
from .ledger import HoldLedger, normalize_order

LEDGER_FILE = 'holds.jsonl'


def _paths(root):
    directory = Path(root)
    return directory, directory / LEDGER_FILE, directory / (LEDGER_FILE + '.lock')


def load(root):
    path = _paths(root)[1]
    if not path.exists():
        return HoldLedger()
    ledger = HoldLedger()
    for line, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not raw.strip():
            continue
        try:
            ledger.register(json.loads(raw))
        except ValueError:
            raise TrialError(f'HOLD_LEDGER_CORRUPT:{line}', 500) from None
    return ledger


def record(root, order):
    """登记单据。文件锁保证并发重试只写入一次，返回 (单据, 是否新登记)。"""
    directory, path, lock_path = _paths(root)
    directory.mkdir(parents=True, exist_ok=True)
    normalized = normalize_order(order)
    with open(lock_path, 'a+') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        ledger = load(directory) if path.exists() else HoldLedger()
        for existing in ledger.orders():
            if existing['order_id'] == normalized['order_id']:
                return existing, False
        temp = Path(NamedTemporaryFile(dir=directory, prefix='holds.', suffix='.tmp', delete=False).name)
        try:
            if path.exists():
                temp.write_bytes(path.read_bytes())
            with temp.open('a', encoding='utf-8') as file:
                file.write(json.dumps(normalized, ensure_ascii=False, separators=(',', ':')) + '\n')
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return normalized, True
