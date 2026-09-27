"""Linux parent-death guard: don't leave a server behind after a client crash."""
import ctypes
import os
import signal
import sys


def main():
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG)")
    if os.getppid() != parent or parent == 1:
        return
    os.execv(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
