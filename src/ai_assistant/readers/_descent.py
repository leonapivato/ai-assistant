"""The atomic descent ADR-0230 §6 requires, and the acquiring open §4 requires.

Both are one operation performed by the kernel, and that is the whole of this
module's subject. §6 is explicit that no ordering of checks and opens establishes
what it needs — "checking a table and then opening a component leaves the same
window at every component it walks: a mount landing between a component's check
and its open is entered before anything refuses it, because refusing to *follow a
symbolic link* is not refusing to *cross a mount*" — so what is required is not a
better order but "a resolution the platform performs atomically".

**Linux's ``openat2`` is the operation, and §6 names it as achievability evidence
rather than as a required construction.** Under ``RESOLVE_NO_XDEV``,
``RESOLVE_NO_SYMLINKS`` and ``RESOLVE_BENEATH`` the kernel refuses *during*
resolution: a mount crossing, a symbolic link at any component, and an escape
above the starting handle each fail the call rather than being noticed after the
fact. There is no window for anything to land in, because there is no pair of
operations.

**Where a platform offers no such operation the mechanism is unavailable on it**
(§6), and that is stated rather than worked around: this module raises
:class:`AtomicDescentUnavailableError` and the fetcher's constructor turns it into
a configuration error. "No lane substitutes a sequence of checks and opens for the
atomic operation on the ground that it is nearly as good; nearly as good is the
defect this clause exists to refuse, and the failure mode stays a legitimate
configuration refused rather than a remote-backed one admitted."

**Why ``ctypes`` and not ``os``.** CPython exposes ``openat`` only through
``os.open(..., dir_fd=…)``, which carries no ``resolve`` word at all — it can be
given ``O_NOFOLLOW``, which guards the *final* component and nothing else, and has
no way to refuse a mount crossing or an escape above the start. There is no
standard-library route to ``openat2``, so the syscall is issued directly. Nothing
else in this module is platform-specific: the call either works or reports
``ENOSYS``/``EPERM``, and the caller refuses.
"""

from __future__ import annotations

import ctypes
import errno
import os
from typing import Final

#: ``__NR_openat2``. The number is 437 on every Linux architecture that has the
#: call — it was added in 5.6 with a single number allocated across the generic
#: and per-architecture tables — so it is a constant rather than a lookup. A
#: kernel without it answers ``ENOSYS``, which is the branch this module is
#: written around; a wrong number on some future architecture would answer
#: ``ENOSYS`` too, which is the safe direction.
_SYS_OPENAT2: Final = 437

#: ``RESOLVE_NO_XDEV`` — refuse to cross a mount point during resolution, the
#: starting point's own mount included. This is what makes the device identity
#: taken from the start handle the device identity of **every** object the
#: resolution can reach (ADR-0230 §6).
RESOLVE_NO_XDEV: Final = 0x01

#: ``RESOLVE_NO_SYMLINKS`` — refuse a symbolic link at **any** component,
#: including the final one, rather than following it. Strictly wider than
#: ``O_NOFOLLOW``, which reaches the last component only (ADR-0230 §6, §4).
RESOLVE_NO_SYMLINKS: Final = 0x04

#: ``RESOLVE_BENEATH`` — refuse any resolution that would escape above the
#: starting handle, which is what ``..`` and an absolute path would do
#: (ADR-0230 §6).
RESOLVE_BENEATH: Final = 0x08

#: The three together: the property ADR-0230 §6 fixes, as one word.
RESOLVE_CONTAINED: Final = RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH


class AtomicDescentUnavailableError(Exception):
    """This platform offers no resolution with ADR-0230 §6's property.

    Not a failure of a particular path: the *operation* is missing, so the
    mechanism is unavailable here. §6 rules that outcome correct rather than a gap
    to fill with an assumption, and the fetcher's constructor translates this into
    a configuration error that stops the deployment.
    """


class _OpenHow(ctypes.Structure):
    """Linux's ``struct open_how`` — three ``__u64`` words, in this order.

    The kernel validates the size it is handed against the size it knows, so a
    mismatched layout is refused with ``E2BIG`` or ``EINVAL`` rather than
    misread. That is why this structure is written out rather than probed.
    """

    _fields_ = (
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    )


def _libc() -> ctypes.CDLL:
    """The process's own C library, for :func:`ctypes.CDLL.syscall`."""
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    library.syscall.argtypes = (
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.POINTER(_OpenHow),
        ctypes.c_size_t,
    )
    return library


def open_contained(start: int, relative: str, *, flags: int) -> int:
    """Resolve ``relative`` beneath ``start`` and open it, atomically. **Blocking**.

    The one operation ADR-0230 §6 requires and ADR-0230 §4's acquisition uses. It
    refuses **rather than resolves** if resolution would cross a mount point,
    follow a symbolic link at any component, or escape above ``start`` — and it
    refuses inside the kernel, during resolution, so there is no interval between
    a check and a use for a mount or a link to land in.

    Args:
        start: An open directory descriptor the resolution begins at. It is never
            escaped: ``RESOLVE_BENEATH`` refuses an absolute path and a ``..``
            that would leave it.
        relative: The path to resolve, relative to ``start``. ``"."`` names the
            starting directory itself.
        flags: The open flags — ``O_RDONLY | O_DIRECTORY | O_CLOEXEC`` for the
            descent's own result, and ``O_RDONLY | O_NONBLOCK | O_CLOEXEC`` for an
            acquisition, where the non-blocking flag is what keeps a named pipe
            with no writer from wedging the call (ADR-0230 §4).

    Returns:
        A new descriptor. The caller owns it and closes it.

    Raises:
        AtomicDescentUnavailableError: If this kernel has no ``openat2`` at all,
            or refuses the ``resolve`` word this module requires. The mechanism is
            unavailable here (ADR-0230 §6).
        OSError: With the kernel's own ``errno`` for every other refusal — the
            refusals that are *about the path*. ``EXDEV`` is a mount crossing,
            ``ELOOP`` a symbolic link, ``EXDEV``/``EAGAIN`` an escape above the
            start on some kernels, ``ENOENT`` an absent component, ``EACCES`` a
            permission denial, ``ENXIO`` an object that cannot be opened as a
            file. Classifying them is the caller's, because what they mean differs
            between the descent and an acquisition.
    """
    library = _libc()
    how = _OpenHow(flags=flags, mode=0, resolve=RESOLVE_CONTAINED)
    encoded = os.fsencode(relative)
    while True:
        ctypes.set_errno(0)
        result = library.syscall(
            _SYS_OPENAT2, start, encoded, ctypes.byref(how), ctypes.sizeof(how)
        )
        if result >= 0:
            return int(result)
        code = ctypes.get_errno()
        if code == errno.EINTR:
            # PEP 475 retries for `os`-level calls; a raw syscall gets none of
            # that, so the retry is written out. A signal is not a refusal.
            continue
        if code in _UNAVAILABLE:
            msg = (
                "this platform offers no atomic contained resolution "
                f"(openat2 answered {errno.errorcode.get(code, code)})"
            )
            raise AtomicDescentUnavailableError(msg)
        raise OSError(code, os.strerror(code), relative)


#: The errors that mean *the operation is missing*, rather than *this path is
#: refused*. ``ENOSYS`` is a kernel without ``openat2``; ``EPERM`` is a seccomp
#: filter or container policy refusing the call itself; ``E2BIG`` and ``EINVAL``
#: are a ``struct open_how`` this kernel does not recognise, i.e. a kernel whose
#: ``openat2`` is not the one this module was written against. Each leaves the
#: mechanism unavailable rather than the path refused, which is the distinction
#: ADR-0230 §6's unavailability clause turns on.
_UNAVAILABLE: Final = frozenset({errno.ENOSYS, errno.EPERM, errno.E2BIG, errno.EINVAL})


def descent_is_available() -> bool:
    """Whether this platform can perform ADR-0230 §6's resolution at all.

    Answered by *doing* it — a contained open of ``"."`` beneath the process's own
    current directory — rather than by reading a version number, because a kernel
    that has the call and a sandbox that refuses it are the same answer to the only
    question this asks. Costs one descriptor, and is called once per fetcher
    construction.
    """
    try:
        probe = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        resolved = open_contained(probe, ".", flags=os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except AtomicDescentUnavailableError:
        return False
    except OSError:
        # The call exists and refused this particular path, which answers the
        # question in the affirmative: the operation is available.
        return True
    else:
        os.close(resolved)
        return True
    finally:
        os.close(probe)
