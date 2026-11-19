"""Cleanup only a test-owned, identity-tracked process family (including onefile bootloader)."""
import psutil


def stop_owned_process(owned):
    try:
        family = owned.children(recursive=True) + [owned]
    except psutil.NoSuchProcess:
        return
    for process in reversed(family):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(family, timeout=5)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError("Test-owned process cleanup did not finish")
