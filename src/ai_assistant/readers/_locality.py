"""Stage 1 of ADR-0230 §6's eligibility: the platform's mount and device tables.

§6 requires that a fetch root's reads "must not leave the device", and decides it
in **two fail-closed stages**. This module is the first: it identifies the mount
the configured path falls under and establishes that **both** its filesystem and
its backing device are local, **opening nothing at all**. A root that is remote as
configured is therefore refused having been touched by nothing — which is what
lets §6 claim the refusal costs the network nothing.

**What the tables say is a claim to be checked, never the thing locality rests
on.** Stage 2 (in :mod:`ai_assistant.readers.files`) opens the mount root this
module names, takes that object's device identity from its handle, and refuses
unless it matches. This module's answer is what that check is *against*.

**The type is necessary and not sufficient** (§6). "An ext4 or XFS volume on an
iSCSI, NBD, NVMe-oF or otherwise network-attached block device reports an ordinary
local type in the platform's mount table while every read of it traverses a
network, and admitting it would be the same ADR-0017 §1 egress the NFS case is,
reached one layer down." So eligibility is decided over the whole backing chain:
the filesystem's type **and** the device behind it, through device-mapper and
software-RAID layers to the hardware underneath.

**Fail-closed, which is what makes this an allow-list rather than a deny-list.**
What is refused is not merely a root the platform reports as remote but "every root
whose locality the platform does not affirmatively establish": an unrecognised
filesystem type, a device chain that reaches no bus this module recognises, a
device that is not in the platform's tables at all. §6 accepts the cost in terms —
"the failure mode is a legitimate local configuration refused until the lane can
establish it — a configuration error a deployment can see and fix — and never a
remote-backed one silently admitted."

**A seam rather than a module of free functions**, because §14 item 22 requires
nine construction arms "over a fetcher whose view of the platform's mount and
device information the test supplies". A deny-list written as one would pass most
of them; what fails an implementation is the *unrecognised* arm and the
ext4-on-iSCSI arm, and neither can be staged on a developer's own disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, final

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Filesystem types whose storage is **memory** and which therefore have no
#: backing device to check: a read of one cannot leave the machine because there is
#: nothing behind it but RAM. Listed separately rather than folded into the block
#: set because the device check below is not merely satisfied for them — it is not
#: applicable, and treating an absent device as "unknown" would refuse them.
_MEMORY_BACKED: Final = frozenset({"tmpfs", "ramfs"})

#: Filesystem types served from a **block device**, for which locality is the
#: device chain's question rather than the type's. An allow-list: a type absent
#: here is refused, so ``nfs``, ``nfs4``, ``cifs``, ``smb3``, ``fuse.sshfs``,
#: ``9p``, ``ceph``, ``glusterfs``, ``afs``, ``overlay`` and everything not yet
#: invented are all refused without being named. Naming them would be the deny-list
#: §6 rules out, and the arm that fails such an implementation is an *unrecognised*
#: type rather than a known-remote one.
_BLOCK_BACKED: Final = frozenset(
    {
        "bcachefs",
        "btrfs",
        "erofs",
        "exfat",
        "ext2",
        "ext3",
        "ext4",
        "f2fs",
        "iso9660",
        "jfs",
        "ntfs3",
        "squashfs",
        "udf",
        "vfat",
        "xfs",
        "zonefs",
    }
)

#: Buses and device classes that establish a device is **attached to this
#: machine**. Reaching one of these while walking a block device's sysfs ancestry,
#: with no network marker on the way, is what "local" means here. ``vmbus`` and
#: ``xen`` are the hypervisor transports a guest's own disk arrives on, which is a
#: virtual machine's equivalent of a PCI slot rather than a network hop.
_LOCAL_BUSES: Final = frozenset(
    {"acpi", "hv", "mmc", "nd", "pci", "platform", "usb", "vio", "virtio", "vmbus", "xen"}
)

#: Kernel block drivers whose device *is* a network client, whatever bus the
#: machine's own hardware sits on. Matched on the device's name because these have
#: no ancestry to walk — they are virtual devices — so the name is the only thing
#: the platform offers.
_NETWORK_BLOCK_PREFIXES: Final = ("nbd", "rbd", "drbd")

#: How many device-mapper / RAID layers this module will walk through before
#: giving up. A stack deeper than this is a chain the platform has not reported
#: through to a conclusion, which §6 refuses.
_MAX_STACK_DEPTH: Final = 8

#: ``/proc/self/mountinfo``'s escaping: a mount point is written with these four
#: characters replaced by their octal escapes, and nothing else is escaped.
_MOUNTINFO_ESCAPES: Final = (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\"))


class DeviceBacking(StrEnum):
    """What the platform says is behind a filesystem's storage (ADR-0230 §6)."""

    LOCAL = "local"
    """Affirmatively established as attached to this machine."""

    NETWORK = "network"
    """Affirmatively established as reached over a network."""

    UNKNOWN = "unknown"
    """The platform would not report through to either conclusion.

    Refused exactly as :attr:`NETWORK` is, which is the fail-closed half: §6
    refuses "every root whose locality the platform does not affirmatively
    establish", so this member is not a third disposition but a second refusal
    with a different explanation for the operator.
    """


@dataclass(frozen=True, slots=True)
class MountClaim:
    """What the platform's tables say about the mount a path falls under.

    A **claim**, and the word is ADR-0230 §6's: nothing here was opened, so
    nothing here is evidence about an object. Stage 2 opens :attr:`mount_point`,
    takes that handle's device identity, and refuses unless it equals
    :attr:`device`.

    Attributes:
        mount_point: The mount's own root, as an absolute path. What stage 2
            opens, and the point the configured path's remainder is resolved
            relative to.
        filesystem_type: The type the mount table names — ``"ext4"``, ``"nfs4"``,
            ``"tmpfs"``. Necessary and not sufficient (§6).
        device: The mount's device identity, in ``st_dev`` form so that stage 2 can
            compare it against ``os.fstat`` of the opened mount root without
            converting either.
        backing: What is behind the filesystem, over the whole chain.
    """

    mount_point: Path
    filesystem_type: str
    device: int
    backing: DeviceBacking

    @property
    def is_local(self) -> bool:
        """Whether **both** halves of §6's eligibility are affirmatively established.

        The type must be one this module recognises as local, and — for a
        block-backed one — the device chain must have reported through to
        :attr:`DeviceBacking.LOCAL`. A memory-backed filesystem has no device to
        check and is local by construction.
        """
        if self.filesystem_type in _MEMORY_BACKED:
            return True
        return self.filesystem_type in _BLOCK_BACKED and self.backing is DeviceBacking.LOCAL


class PlatformTables(Protocol):
    """The fetcher's view of the platform's mount and device information.

    A seam rather than a call into :mod:`os`, because ADR-0230 §14 item 22 requires
    nine construction arms over "a fetcher whose view of the platform's mount and
    device information the test supplies": a root on a filesystem reported as
    network-attached, one whose type is unrecognised, one on an allow-listed type
    over a network-attached device, and one that constructs. None of the first
    three can be staged on a developer's own disk, and an implementation with no
    seam here is one whose fail-closed property is untestable.

    Confined to `readers` deliberately: it is one concrete fetcher's platform
    dependency, not a contract between subsystems, so it is not a `core` Protocol
    (ADR-0093 §2, golden rule 1).
    """

    def claim_for(self, path: Path) -> MountClaim | None:
        """What the tables say about the mount ``path`` falls under.

        Args:
            path: The configured root, absolute and **not** canonicalised —
                resolving it would follow the symbolic links §6 requires the
                descent to refuse.

        Returns:
            The claim, or ``None`` where the tables name no mount for this path at
            all. ``None`` is a refusal like any other: §6 admits nothing whose
            locality the platform does not establish.
        """
        ...


def _unescape(field: str) -> str:
    """Decode ``mountinfo``'s four octal escapes, and only those four."""
    for escape, literal in _MOUNTINFO_ESCAPES:
        field = field.replace(escape, literal)
    return field


def _under(candidate: Path, path: Path) -> bool:
    """Whether ``path`` lies at or under ``candidate``, textually.

    Textual and not ``Path.resolve``-based, deliberately: resolving would follow
    symbolic links, and §6 requires a link at any component of the configured path
    to *refuse* rather than be followed. A configured path whose ancestor is a link
    therefore lands on the mount its **text** falls under, and stage 2's descent
    refuses it — which is the arm ADR-0230 §14 item 22 calls the seventh.
    """
    return candidate == path or candidate in path.parents


@final
class ProcPlatformTables:
    """The platform's tables as Linux publishes them, in ``/proc`` and ``/sys``.

    ``/proc/self/mountinfo`` for the mount a path falls under, its type and its
    device identity; ``/sys/dev/block`` and ``/sys/class/block`` for what is behind
    that device. Both are reads of the kernel's own reporting surfaces: nothing
    under the configured path, nothing under the mount root, and no ``open`` of
    either (ADR-0230 §6 stage 1).
    """

    def __init__(self, *, mountinfo: Path | None = None, sysfs: Path | None = None) -> None:
        """Create a view over this machine's own reporting surfaces.

        Args:
            mountinfo: Where the mount table lives. Defaulted rather than fixed so
                a test can drive the *parser* over a captured table; the locality
                arms drive the seam above instead.
            sysfs: Where the device tree lives, for the same reason.
        """
        self._mountinfo = mountinfo if mountinfo is not None else Path("/proc/self/mountinfo")
        self._sysfs = sysfs if sysfs is not None else Path("/sys")

    def claim_for(self, path: Path) -> MountClaim | None:
        """The mount ``path`` falls under, with its type and its backing chain."""
        best: _MountRow | None = None
        for line in self._read_mountinfo():
            row = _parse_mountinfo_line(line)
            if row is None or not _under(row.mount_point, path):
                continue
            # `>=` rather than `>`: a later row for the same mount point is an
            # over-mount, and the last one wins because it is what a resolution
            # would reach.
            if best is None or len(row.mount_point.parts) >= len(best.mount_point.parts):
                best = row
        if best is None:
            return None
        backing = (
            DeviceBacking.LOCAL
            if best.filesystem_type in _MEMORY_BACKED
            else self._backing_of(best.device, best.source)
        )
        return MountClaim(
            mount_point=best.mount_point,
            filesystem_type=best.filesystem_type,
            device=best.device,
            backing=backing,
        )

    def _read_mountinfo(self) -> list[str]:
        """The mount table's lines, or none where it cannot be read.

        An unreadable table is not an error here: it leaves the claim ``None``,
        which refuses the root. That is the fail-closed direction.
        """
        try:
            return self._mountinfo.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def _backing_of(self, device: int, source: str) -> DeviceBacking:
        """Walk a block device's chain and say what is behind it.

        Args:
            device: The mount's ``st_dev``-form device identity.
            source: The mount table's source field — ``/dev/sda2``, ``none``. Used
                only where the device identity is anonymous, which is what a
                multi-device filesystem such as ``btrfs`` reports.

        Returns:
            :attr:`DeviceBacking.NETWORK` where any layer of the chain is a network
            client, :attr:`DeviceBacking.LOCAL` where the chain reaches a bus this
            machine has, and :attr:`DeviceBacking.UNKNOWN` where it reports through
            to neither.
        """
        node = self._block_node(device, source)
        if node is None:
            return DeviceBacking.UNKNOWN
        return self._walk(node, depth=0)

    def _block_node(self, device: int, source: str) -> Path | None:
        """The ``sysfs`` directory for a mount's block device, if it has one."""
        by_number = self._sysfs / "dev" / "block" / f"{os.major(device)}:{os.minor(device)}"
        if by_number.exists():
            return by_number
        # An anonymous device number — `btrfs` and every FUSE filesystem report
        # one — so fall back to the source's own name. Read out of `sysfs` by
        # name rather than by `stat`-ing the node under `/dev`, which keeps this
        # stage to reads of the kernel's reporting surfaces.
        if source.startswith("/dev/"):
            by_name = self._sysfs / "class" / "block" / Path(source).name
            if by_name.exists():
                return by_name
        return None

    def _walk(self, node: Path, *, depth: int) -> DeviceBacking:
        """Classify one block device, following stacked layers to what is under them."""
        if depth > _MAX_STACK_DEPTH:
            return DeviceBacking.UNKNOWN
        try:
            resolved = node.resolve(strict=True)
        except OSError:
            return DeviceBacking.UNKNOWN
        if resolved.name.startswith(_NETWORK_BLOCK_PREFIXES):
            return DeviceBacking.NETWORK
        slaves = self._slaves(resolved)
        if slaves is None:
            # The stack could not be read, so what is under this device is not a
            # question this platform answered. Not a leaf.
            return DeviceBacking.UNKNOWN
        if slaves:
            return self._combine(self._walk(slave, depth=depth + 1) for slave in sorted(slaves))
        return self._classify_ancestry(resolved)

    def _slaves(self, resolved: Path) -> list[Path] | None:
        """The devices a stacked device sits on — LVM, dm-crypt, software RAID.

        §6 decides eligibility "over the whole backing chain", and a
        device-mapper or RAID device *is* a chain: an encrypted ext4 volume on an
        iSCSI LUN reports ``dm-0`` in the mount table and says nothing about the
        network underneath it. Walking the slaves is what reaches the layer the
        question is actually about.

        Returns:
            The stacked layers, empty for a leaf device, or ``None`` where the
            directory exists and could not be read — which is a chain the platform
            did not report through and is refused rather than treated as a leaf.
        """
        holder = resolved / "slaves"
        try:
            return [entry for entry in holder.iterdir() if entry.is_dir()]
        except FileNotFoundError:
            # A device with no `slaves` directory is a leaf, which is an answer
            # rather than a failure to answer.
            return []
        except OSError:
            return None

    def _classify_ancestry(self, resolved: Path) -> DeviceBacking:
        """Walk a leaf block device's ``sysfs`` ancestry for a bus or a transport.

        Upwards from the device node to ``/sys/devices``, stopping at the **first**
        answer: a network transport anywhere on the way refuses, and a recognised
        local bus admits. Ending the walk with neither is
        :attr:`DeviceBacking.UNKNOWN`, which refuses too — a chain the platform did
        not report through to a conclusion (§6).
        """
        try:
            devices_root = (self._sysfs / "devices").resolve(strict=True)
        except OSError:
            return DeviceBacking.UNKNOWN
        current = resolved
        while current not in (devices_root, current.parent):
            subsystem = self._subsystem_of(current)
            if subsystem is None:
                # The node's own membership could not be read, so neither the
                # transport check below nor the bus check can be performed on it —
                # and walking past it to an ancestor would admit a controller whose
                # attachment is exactly what could not be established.
                return DeviceBacking.UNKNOWN
            transport = self._transport_of(current, subsystem)
            if transport is not None:
                # `NETWORK` **and** `UNKNOWN` both stop the walk here, and that is
                # the fail-closed half. A node whose transport evidence could not be
                # read is a node this platform did not report through, and walking
                # past it to a `pci` ancestor above would convert "we could not tell"
                # into "local" — admitting an NVMe-oF or iSCSI device on a transient
                # permission or I/O failure, which is exactly the egress §6 exists to
                # refuse.
                return transport
            if subsystem in _LOCAL_BUSES:
                return DeviceBacking.LOCAL
            current = current.parent
        return DeviceBacking.UNKNOWN

    def _transport_of(self, node: Path, subsystem: str) -> DeviceBacking | None:
        """What this ancestor's transport says, or ``None`` where it says nothing.

        An iSCSI or FCoE initiator publishes its host under ``/sys/class/iscsi_host``
        or ``/sys/class/fc_host``; an NVMe controller publishes a ``transport`` file
        reading something other than ``pcie`` — ``rdma``, ``tcp``, ``fc``. Both are the
        "ext4 on a network-attached block device" case §6 names, and both are invisible
        to the mount table's type.

        **A verdict this cannot reach is ``UNKNOWN`` and never silence**, which is the
        distinction the whole method turns on. ``Path.exists()`` answers ``False`` for
        *both* "there is no such host" and "the directory holding it could not be
        read", and a ``transport`` file that raises answers nothing at all — so a
        method returning a boolean would let a transient permission or I/O failure on a
        network-attached controller fall through to a ``pci`` ancestor and be admitted
        as local. §6 refuses "**every** root whose locality the platform does not
        affirmatively establish", so an unreadable answer is refused exactly as a
        remote one is.

        The ``transport`` read is scoped to an ``nvme`` node rather than tried on every
        ancestor, so an unrelated file of that name elsewhere in the device tree cannot
        be read as a verdict.

        Returns:
            :attr:`DeviceBacking.NETWORK` where a network transport is established,
            :attr:`DeviceBacking.UNKNOWN` where the evidence exists and could not be
            read, and ``None`` where this node carries no transport evidence at all —
            which is the ordinary case for every ancestor that is not a host.
        """
        for kind in ("iscsi_host", "fc_host"):
            hosts = self._hosts_of(kind, node.name)
            if hosts is not None:
                return hosts
        if subsystem != "nvme":
            return None
        try:
            declared = (node / "transport").read_text(encoding="utf-8").strip()
        except OSError:
            # Including `FileNotFoundError`: an NVMe controller with no `transport`
            # attribute is one this kernel will not say the attachment of, and §6's
            # failure mode is "a legitimate local configuration refused until the lane
            # can establish it" rather than a remote-backed one admitted.
            return DeviceBacking.UNKNOWN
        return None if declared == "pcie" else DeviceBacking.NETWORK

    def _hosts_of(self, kind: str, name: str) -> DeviceBacking | None:
        """Whether ``name`` is a host of a network transport class, if that is readable.

        Returns:
            :attr:`DeviceBacking.NETWORK` where the class holds this host,
            :attr:`DeviceBacking.UNKNOWN` where the class directory exists and could
            not be listed, and ``None`` where the class does not exist at all — which
            means this kernel has no such transport, and is an answer rather than a
            failure to answer.
        """
        directory = self._sysfs / "class" / kind
        try:
            present = {entry.name for entry in directory.iterdir()}
        except FileNotFoundError:
            return None
        except OSError:
            return DeviceBacking.UNKNOWN
        return DeviceBacking.NETWORK if name in present else None

    @staticmethod
    def _subsystem_of(node: Path) -> str | None:
        """The name of the bus or class a ``sysfs`` node belongs to.

        **Three answers and not two**, for :meth:`_transport_of`'s reason one level up:
        a node that belongs to no subsystem and a node whose membership could not be
        read are different facts, and collapsing them lets the second be walked past.
        That matters most on exactly the node it matters on: an NVMe-oF controller
        whose ``subsystem`` link cannot be resolved would not be recognised as an
        ``nvme`` node, its ``transport`` attribute would never be read, and the walk
        would reach the ``pci`` ancestor above it and answer ``LOCAL`` — admitting a
        network-attached device *because* its evidence was unavailable, which is the
        inverse of what ADR-0230 §6 requires.

        Returns:
            The subsystem's name; ``""`` where the node declares none, which is the
            ordinary case for an intermediate node and is an answer; or ``None`` where
            the link exists and could not be resolved, which is not.
        """
        try:
            return (node / "subsystem").resolve(strict=True).name
        except FileNotFoundError:
            # No `subsystem` link at all: this node belongs to no bus and no class,
            # which is what most intermediate nodes of a device path are.
            return ""
        except OSError:
            return None

    @staticmethod
    def _combine(verdicts: Iterable[DeviceBacking]) -> DeviceBacking:
        """Fold a stacked device's layers: any network wins, then any unknown.

        Every layer must be local for the stack to be local, which is the
        fail-closed direction and the one §6 requires: a RAID-1 mirror of a local
        disk and an iSCSI LUN is reachable over a network.
        """
        seen = set(verdicts)
        if not seen:
            return DeviceBacking.UNKNOWN
        if DeviceBacking.NETWORK in seen:
            return DeviceBacking.NETWORK
        if DeviceBacking.UNKNOWN in seen:
            return DeviceBacking.UNKNOWN
        return DeviceBacking.LOCAL


@dataclass(frozen=True, slots=True)
class _MountRow:
    """One ``mountinfo`` row, reduced to the four fields this module reads."""

    mount_point: Path
    filesystem_type: str
    device: int
    source: str


#: How many space-separated fields a ``mountinfo`` row carries before its ``" - "``
#: separator, and after it, at the least. The pre-separator fields are the mount
#: id, the parent id, ``major:minor``, the root within the filesystem and the mount
#: point; the post-separator ones are the type and the source. Optional fields sit
#: between the fifth and the separator, which is why the separator is what the row
#: is split on rather than a fixed index.
_MOUNTINFO_LEADING_FIELDS: Final = 5
_MOUNTINFO_TRAILING_FIELDS: Final = 2


def _parse_mountinfo_line(line: str) -> _MountRow | None:
    """One ``mountinfo`` row, or ``None`` for a row this parser cannot read.

    ``None`` refuses rather than guesses: a row it cannot read is a mount it
    cannot vouch for, and §6's fail-closed rule makes that a refusal.
    """
    head, separator, tail = line.partition(" - ")
    if not separator:
        return None
    left = head.split(" ")
    right = tail.split(" ")
    if len(left) < _MOUNTINFO_LEADING_FIELDS or len(right) < _MOUNTINFO_TRAILING_FIELDS:
        return None
    major, colon, minor = left[2].partition(":")
    if not colon:
        return None
    try:
        device = os.makedev(int(major), int(minor))
    except ValueError:
        return None
    return _MountRow(
        mount_point=Path(_unescape(left[4])),
        filesystem_type=right[0],
        device=device,
        source=_unescape(right[1]),
    )
