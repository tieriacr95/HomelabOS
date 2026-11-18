#!/usr/bin/env python3
"""Fixed, optional weekly restic verification job. No arbitrary commands."""
import json
import sys

try:
    from . import backup_manager
except ImportError:
    import backup_manager


def run():
    """Use the same lock, job history and integration as manual verification."""
    job = backup_manager.start("verify","VERIFICAR RESPALDOS",background=False)
    print(json.dumps({"id":job["id"],"state":job["state"]},
                     ensure_ascii=False))
    return 0 if job["state"]=="success" else 1


if __name__=="__main__":
    sys.exit(run())
