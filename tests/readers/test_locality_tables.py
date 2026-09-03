"""``ProcPlatformTables`` over a sysfs a test builds (ADR-0230 §6, stage 1).

``tests/readers/test_fetcher_locality.py`` drives the nine construction arms §14 item
22 names, over a **supplied** platform view — which is what that item requires and what
makes those arms portable. This file drives the thing that produces such a view on a
real machine: the parser and the device walk themselves, over ``/proc`` and ``/sys``
trees this test lays out.

**Why it is worth its own file.** The seam exists so the fetcher's arms need no
particular hardware; the consequence is that ``ProcPlatformTables`` is exercised by
almost nothing else, and it is the component that decides — on the one deployment that
matters — whether a root's reads can leave the device. Its every branch is a
fail-closed judgement, and a fail-closed judgement that silently became permissive
would be invisible to every other test in this package.

**The arms are drawn where §6 draws them.** A filesystem type is "necessary and **not**
sufficient"; eligibility is decided "over the whole backing chain and not over the
filesystem's type alone"; and what is refused is "**every** root whose locality the
platform does not affirmatively establish" — so the cases that matter most are the ones
where the platform answers *nothing*, not the ones where it answers *remote*.
"""

from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

import pytest

from ai_assistant.readers._locality import DeviceBacking, ProcPlatformTables

if TYPE_CHECKING:
    from pathlib import Path

#: The device the fixtures below put the root's mount on, in ``major:minor`` form and
#: in the ``st_dev`` form a claim carries.
_MAJOR, _MINOR = 259, 0
_DEVICE = os.makedev(_MAJOR, _MINOR)

#: Where the fixture mounts the root. Its own path never reaches the filesystem in
#: stage 1 — the tables are read and nothing is opened — so it need not exist.
_MOUNT = "/srv/documents"


class Sysfs:
    """A ``/sys`` tree laid out by hand, plus the ``mountinfo`` row that names it."""

    def __init__(self, tmp_path: Path) -> None:
        """Create the skeleton every arm shares: a devices root, and a class directory."""
        self.root = tmp_path / "sys"
        (self.root / "devices").mkdir(parents=True)
        (self.root / "class").mkdir()
        (self.root / "dev" / "block").mkdir(parents=True)
        self.mountinfo = tmp_path / "mountinfo"

    def bus(self, name: str) -> Path:
        """Declare a bus, so a device may name it as its subsystem."""
        path = self.root / "bus" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def klass(self, name: str) -> Path:
        """Declare a device class — ``block``, ``nvme``, ``iscsi_host``."""
        path = self.root / "class" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def device(self, relative: str, *, subsystem: Path) -> Path:
        """Create one device node under ``devices``, belonging to ``subsystem``."""
        path = self.root / "devices" / relative
        path.mkdir(parents=True, exist_ok=True)
        (path / "subsystem").symlink_to(subsystem, target_is_directory=True)
        return path

    def block(self, node: Path) -> None:
        """Point ``/sys/dev/block/<major>:<minor>`` at ``node``."""
        (self.root / "dev" / "block" / f"{_MAJOR}:{_MINOR}").symlink_to(
            node, target_is_directory=True
        )

    def mounted(self, filesystem_type: str = "ext4", source: str = "/dev/nvme0n1") -> None:
        """Write the one ``mountinfo`` row the root's mount is read from."""
        self.mountinfo.write_text(
            f"36 35 {_MAJOR}:{_MINOR} / {_MOUNT} rw,relatime - {filesystem_type} {source} rw\n",
            encoding="utf-8",
        )

    def tables(self) -> ProcPlatformTables:
        """The subject, reading this tree and nothing of the real machine."""
        return ProcPlatformTables(mountinfo=self.mountinfo, sysfs=self.root)


def _nvme(sysfs: Sysfs, *, transport: str | None) -> Path:
    """A PCI-parented NVMe controller and its namespace, optionally declaring a transport."""
    sysfs.device("pci0000:00", subsystem=sysfs.bus("pci"))
    controller = sysfs.device("pci0000:00/nvme/nvme0", subsystem=sysfs.klass("nvme"))
    if transport is not None:
        (controller / "transport").write_text(transport, encoding="utf-8")
    namespace = sysfs.device("pci0000:00/nvme/nvme0/nvme0n1", subsystem=sysfs.klass("block"))
    sysfs.block(namespace)
    sysfs.mounted()
    return controller


def _backing(sysfs: Sysfs) -> DeviceBacking | None:
    """The verdict the tables reach for the configured root, or ``None`` for no mount."""
    claim = sysfs.tables().claim_for(pathlib.Path(_MOUNT) / "reports")
    return None if claim is None else claim.backing


# --- what the platform affirmatively establishes ----------------------------


def test_an_nvme_controller_over_pcie_is_local(tmp_path: Path) -> None:
    """The positive arm: a transport that says ``pcie``, under a bus this machine has.

    Present so the refusals below are not vacuous — a walk that answered ``UNKNOWN``
    for everything would pass every other case in this file.
    """
    sysfs = Sysfs(tmp_path)
    _nvme(sysfs, transport="pcie")

    assert _backing(sysfs) is DeviceBacking.LOCAL


@pytest.mark.parametrize("transport", ["tcp", "rdma", "fc", "loop"])
def test_an_nvme_controller_over_a_fabric_is_network(tmp_path: Path, transport: str) -> None:
    """NVMe-oF: an ordinary local filesystem type over a device reached by network.

    §6's own case, reached one layer below the mount table: "an ext4 or XFS volume on an
    iSCSI, NBD, NVMe-oF or otherwise network-attached block device reports an ordinary
    local type in the platform's mount table while every read of it traverses a
    network". The allow-list admits the *type* here; the chain is what refuses.
    """
    sysfs = Sysfs(tmp_path)
    _nvme(sysfs, transport=transport)

    assert _backing(sysfs) is DeviceBacking.NETWORK


def test_an_nvme_controller_declaring_no_transport_is_unknown(tmp_path: Path) -> None:
    """The fail-closed arm the boolean form of this check got wrong.

    A controller with no ``transport`` attribute is one this kernel will not say the
    attachment of. A walk that read the absence as "not network" would carry on to the
    ``pci`` ancestor above and answer ``LOCAL`` — converting *we could not tell* into
    *local*, which is precisely what §6 refuses: "**every** root whose locality the
    platform does not affirmatively establish".
    """
    sysfs = Sysfs(tmp_path)
    _nvme(sysfs, transport=None)

    assert _backing(sysfs) is DeviceBacking.UNKNOWN


def test_an_nvme_controller_whose_transport_cannot_be_read_is_unknown(tmp_path: Path) -> None:
    """The same hole reached by a transient failure rather than by an absence.

    A permission or I/O failure reading the attribute of a **network-attached**
    controller must not admit it. This is the arm that fails on any implementation
    treating an unreadable answer as a negative one.
    """
    if os.geteuid() == 0:
        pytest.skip("a permission denial cannot be staged as root")
    sysfs = Sysfs(tmp_path)
    controller = _nvme(sysfs, transport="tcp")
    (controller / "transport").chmod(0o000)
    try:
        verdict = _backing(sysfs)
    finally:
        (controller / "transport").chmod(0o600)

    assert verdict is DeviceBacking.UNKNOWN


# --- the SCSI transports, and the same hole on the class directory ----------


def test_a_host_listed_under_iscsi_host_is_network(tmp_path: Path) -> None:
    """An iSCSI initiator publishes its host, and a local bus above it changes nothing."""
    sysfs = Sysfs(tmp_path)
    sysfs.device("pci0000:00", subsystem=sysfs.bus("pci"))
    host = sysfs.device("pci0000:00/host0", subsystem=sysfs.klass("scsi"))
    disk = sysfs.device("pci0000:00/host0/target0:0:0/sda", subsystem=sysfs.klass("block"))
    (sysfs.klass("iscsi_host") / host.name).mkdir()
    sysfs.block(disk)
    sysfs.mounted(source="/dev/sda")

    assert _backing(sysfs) is DeviceBacking.NETWORK


def test_a_host_class_that_cannot_be_listed_is_unknown(tmp_path: Path) -> None:
    """``Path.exists()`` answers ``False`` for two different things, and only one is an answer.

    "There is no such host" and "the directory holding it could not be read" are the
    same boolean and opposite verdicts. This is the arm that fails on any
    implementation that asks the question with ``exists``.
    """
    if os.geteuid() == 0:
        pytest.skip("a permission denial cannot be staged as root")
    sysfs = Sysfs(tmp_path)
    sysfs.device("pci0000:00", subsystem=sysfs.bus("pci"))
    host = sysfs.device("pci0000:00/host0", subsystem=sysfs.klass("scsi"))
    disk = sysfs.device("pci0000:00/host0/target0:0:0/sda", subsystem=sysfs.klass("block"))
    hosts = sysfs.klass("iscsi_host")
    (hosts / host.name).mkdir()
    sysfs.block(disk)
    sysfs.mounted(source="/dev/sda")
    hosts.chmod(0o000)
    try:
        verdict = _backing(sysfs)
    finally:
        hosts.chmod(0o700)

    assert verdict is DeviceBacking.UNKNOWN


def test_a_kernel_with_no_iscsi_class_at_all_is_not_refused_for_it(tmp_path: Path) -> None:
    """A class that does not exist means the kernel has no such transport.

    That **is** an answer, and reading it as "we could not tell" would refuse every
    ordinary machine whose kernel was built without iSCSI — which is a fail-closed rule
    turned into a fail-always one.
    """
    sysfs = Sysfs(tmp_path)
    _nvme(sysfs, transport="pcie")

    assert not (sysfs.root / "class" / "iscsi_host").exists()
    assert _backing(sysfs) is DeviceBacking.LOCAL


# --- stacked devices: the whole backing chain (ADR-0230 §6) -----------------


def _stack(sysfs: Sysfs, *, transports: list[str | None]) -> None:
    """A device-mapper device over one NVMe controller per entry in ``transports``."""
    mapped = sysfs.device("virtual/block/dm-0", subsystem=sysfs.klass("block"))
    (mapped / "slaves").mkdir()
    sysfs.device("pci0000:00", subsystem=sysfs.bus("pci"))
    for index, transport in enumerate(transports):
        controller = sysfs.device(f"pci0000:00/nvme/nvme{index}", subsystem=sysfs.klass("nvme"))
        if transport is not None:
            (controller / "transport").write_text(transport, encoding="utf-8")
        namespace = sysfs.device(
            f"pci0000:00/nvme/nvme{index}/nvme{index}n1", subsystem=sysfs.klass("block")
        )
        (mapped / "slaves" / namespace.name).symlink_to(namespace, target_is_directory=True)
    sysfs.block(mapped)
    sysfs.mounted(source="/dev/dm-0")


@pytest.mark.parametrize(
    ("transports", "expected"),
    [
        (["pcie", "pcie"], DeviceBacking.LOCAL),
        (["pcie", "tcp"], DeviceBacking.NETWORK),
        (["pcie", None], DeviceBacking.UNKNOWN),
        ([None, "tcp"], DeviceBacking.NETWORK),
    ],
)
def test_a_stacked_device_is_decided_over_every_layer(
    tmp_path: Path, transports: list[str | None], expected: DeviceBacking
) -> None:
    """§6: eligibility is decided "over the whole backing chain".

    "An encrypted ext4 volume on an iSCSI LUN reports ``dm-0`` in the mount table and
    says nothing about the network underneath it", and a RAID-1 mirror of a local disk
    and a remote LUN is reachable over a network. So every layer must be local for the
    stack to be local, any network layer refuses, and any unknown layer refuses —
    with network taking precedence over unknown, because it is the more specific
    statement of the same refusal.
    """
    sysfs = Sysfs(tmp_path)
    _stack(sysfs, transports=transports)

    assert _backing(sysfs) is expected


def test_a_stack_whose_layers_cannot_be_listed_is_unknown(tmp_path: Path) -> None:
    """An unreadable ``slaves`` directory is not a leaf device.

    Reading it as one would classify a device-mapper volume by its own ancestry —
    ``/sys/devices/virtual/block``, which reaches no bus — and, on a device that *did*
    sit on a local bus, would answer ``LOCAL`` for a stack whose layers were never
    seen.
    """
    if os.geteuid() == 0:
        pytest.skip("a permission denial cannot be staged as root")
    sysfs = Sysfs(tmp_path)
    _stack(sysfs, transports=["pcie"])
    slaves = sysfs.root / "devices" / "virtual" / "block" / "dm-0" / "slaves"
    slaves.chmod(0o000)
    try:
        verdict = _backing(sysfs)
    finally:
        slaves.chmod(0o700)

    assert verdict is DeviceBacking.UNKNOWN


# --- the network block drivers, and the fail-closed default -----------------


@pytest.mark.parametrize("name", ["nbd0", "rbd1", "drbd2"])
def test_a_network_block_driver_is_refused_by_name(tmp_path: Path, name: str) -> None:
    """These have no ancestry to walk: they are virtual devices, and the name is all there is."""
    sysfs = Sysfs(tmp_path)
    device = sysfs.device(f"virtual/block/{name}", subsystem=sysfs.klass("block"))
    sysfs.block(device)
    sysfs.mounted(source=f"/dev/{name}")

    assert _backing(sysfs) is DeviceBacking.NETWORK


def test_a_device_reaching_no_recognised_bus_is_unknown(tmp_path: Path) -> None:
    """The default, and it is a refusal: a loop device, a bus nobody has heard of.

    §6 accepts the cost in terms — "the failure mode is a legitimate local configuration
    refused until the lane can establish it — a configuration error a deployment can see
    and fix — and never a remote-backed one silently admitted".
    """
    sysfs = Sysfs(tmp_path)
    device = sysfs.device("virtual/block/loop0", subsystem=sysfs.klass("block"))
    sysfs.block(device)
    sysfs.mounted(source="/dev/loop0")

    assert _backing(sysfs) is DeviceBacking.UNKNOWN


def test_a_device_absent_from_the_platforms_tables_is_unknown(tmp_path: Path) -> None:
    """No ``/sys/dev/block`` entry and no named source: nothing to report through."""
    sysfs = Sysfs(tmp_path)
    sysfs.mounted(source="none")

    assert _backing(sysfs) is DeviceBacking.UNKNOWN


# --- the mount table itself -------------------------------------------------


def test_a_memory_backed_filesystem_needs_no_device(tmp_path: Path) -> None:
    """``tmpfs`` has nothing behind it but RAM, so the device half is not applicable.

    Treating its absent device as *unknown* would refuse a filesystem that cannot leave
    the machine by construction — which is the one case where the device check is not
    merely satisfied but inapplicable.
    """
    sysfs = Sysfs(tmp_path)
    sysfs.mounted(filesystem_type="tmpfs", source="none")

    claim = sysfs.tables().claim_for(pathlib.Path(_MOUNT))
    assert claim is not None
    assert claim.backing is DeviceBacking.LOCAL
    assert claim.is_local


@pytest.mark.parametrize("filesystem_type", ["nfs4", "cifs", "fuse.sshfs", "9p", "somefs-9000"])
def test_a_type_outside_the_allow_list_is_not_local_however_the_device_reads(
    tmp_path: Path, filesystem_type: str
) -> None:
    """The type is "necessary and **not** sufficient", and the allow-list is fail-closed.

    ``somefs-9000`` is the arm that fails a deny-list: it is a filesystem nobody has
    heard of, and an implementation enumerating the *remote* types would admit it.
    """
    sysfs = Sysfs(tmp_path)
    _nvme(sysfs, transport="pcie")
    sysfs.mounted(filesystem_type=filesystem_type)

    claim = sysfs.tables().claim_for(pathlib.Path(_MOUNT))
    assert claim is not None
    assert claim.filesystem_type == filesystem_type
    assert not claim.is_local


def test_the_deepest_matching_mount_wins_and_an_over_mount_wins_over_it(
    tmp_path: Path,
) -> None:
    """A path falls under the mount a resolution would actually reach.

    Two rules, and both matter: a nested mount is deeper than its parent and takes it,
    and a **later** row for the same mount point is an over-mount that takes the
    earlier one — which is what a resolution starting at that path would land on.
    """
    sysfs = Sysfs(tmp_path)
    sysfs.mountinfo.write_text(
        "1 0 0:1 / / rw - ext4 /dev/sda rw\n"
        f"2 1 0:2 / {_MOUNT} rw - ext4 /dev/sdb rw\n"
        f"3 1 0:3 / {_MOUNT} rw - tmpfs none rw\n"
        "4 1 0:4 / /other rw - ext4 /dev/sdc rw\n",
        encoding="utf-8",
    )

    claim = sysfs.tables().claim_for(pathlib.Path(_MOUNT) / "reports")

    assert claim is not None
    assert (str(claim.mount_point), claim.filesystem_type) == (_MOUNT, "tmpfs")


def test_a_mount_point_carrying_an_escaped_space_is_read_back(tmp_path: Path) -> None:
    """``mountinfo`` escapes four characters, and a path holding one is still a path."""
    sysfs = Sysfs(tmp_path)
    sysfs.mountinfo.write_text(
        "1 0 0:1 / /srv/my\\040documents rw - tmpfs none rw\n", encoding="utf-8"
    )

    claim = sysfs.tables().claim_for(pathlib.Path("/srv/my documents/a"))

    assert claim is not None
    assert str(claim.mount_point) == "/srv/my documents"


@pytest.mark.parametrize(
    "row",
    [
        "not a mountinfo row at all",
        "1 0 zz:1 / /srv rw - ext4 /dev/sda rw",
        "1 0 0:1 / /srv rw ext4 /dev/sda rw",
        "1 0 0:1 - ext4",
    ],
)
def test_a_row_this_parser_cannot_read_names_no_mount(tmp_path: Path, row: str) -> None:
    """ "A row it cannot read is a mount it cannot vouch for", so it refuses rather than guesses."""
    sysfs = Sysfs(tmp_path)
    sysfs.mountinfo.write_text(f"{row}\n", encoding="utf-8")

    assert sysfs.tables().claim_for(pathlib.Path("/srv/reports")) is None


def test_an_unreadable_mount_table_names_no_mount(tmp_path: Path) -> None:
    """The whole of stage 1 unavailable is a refusal, which is the fail-closed direction."""
    sysfs = Sysfs(tmp_path)

    assert sysfs.tables().claim_for(pathlib.Path("/srv/reports")) is None


def test_a_controller_whose_subsystem_cannot_be_read_is_unknown(tmp_path: Path) -> None:
    """The third face of the same hole, on the node's own membership.

    ``_subsystem_of`` decides *which* checks apply to a node. A controller whose
    ``subsystem`` link cannot be resolved is not recognised as an ``nvme`` node, so its
    ``transport`` attribute is never read — and a walk that carried on would reach the
    ``pci`` ancestor above and answer ``LOCAL``, admitting a network-attached device
    **because** its evidence was unavailable. That is the inverse of ADR-0230 §6's rule.

    The controller here really is on a fabric, so what the arm distinguishes is a
    verdict of ``UNKNOWN`` from a verdict of ``LOCAL`` on a device that must never be
    admitted, rather than a shade of caution on one that could be.
    """
    if os.geteuid() == 0:
        pytest.skip("a permission denial cannot be staged as root")
    sysfs = Sysfs(tmp_path)
    controller = _nvme(sysfs, transport="tcp")
    controller.chmod(0o000)
    try:
        verdict = _backing(sysfs)
    finally:
        controller.chmod(0o700)

    assert verdict is DeviceBacking.UNKNOWN


def test_a_node_declaring_no_subsystem_at_all_is_walked_past(tmp_path: Path) -> None:
    """The other half of the pair, so the refusal above is not a fail-always rule.

    Most intermediate nodes of a device path declare no ``subsystem`` link, and reading
    that absence as "could not be read" would refuse every machine — turning a
    fail-closed rule into one that admits nothing at all. The chain here carries such a
    node between the namespace and the bus, and still reaches ``LOCAL``.
    """
    sysfs = Sysfs(tmp_path)
    sysfs.device("pci0000:00", subsystem=sysfs.bus("pci"))
    # An intermediate node with no `subsystem` link of its own.
    (sysfs.root / "devices" / "pci0000:00" / "nvme").mkdir(parents=True, exist_ok=True)
    controller = sysfs.device("pci0000:00/nvme/nvme0", subsystem=sysfs.klass("nvme"))
    (controller / "transport").write_text("pcie", encoding="utf-8")
    namespace = sysfs.device("pci0000:00/nvme/nvme0/nvme0n1", subsystem=sysfs.klass("block"))
    sysfs.block(namespace)
    sysfs.mounted()

    assert not (sysfs.root / "devices" / "pci0000:00" / "nvme" / "subsystem").exists()
    assert _backing(sysfs) is DeviceBacking.LOCAL


def test_a_controller_whose_subsystem_link_dangles_is_unknown(tmp_path: Path) -> None:
    """An absent link and a dangling one are the same ``FileNotFoundError``.

    ``Path.resolve(strict=True)`` raises it for a ``subsystem`` link that is not there
    **and** for one whose target does not resolve, and only the first means "belongs to
    no subsystem". Reading the second that way skips the NVMe transport check on a
    fabric-attached controller and lets the walk reach the ``pci`` ancestor above —
    admitting the device precisely because its evidence was unavailable.

    Staged without privilege, which is what makes it a real arm rather than a pinned
    constant: the link is simply pointed at a directory that does not exist.
    """
    sysfs = Sysfs(tmp_path)
    controller = _nvme(sysfs, transport="tcp")
    (controller / "subsystem").unlink()
    (controller / "subsystem").symlink_to(sysfs.root / "class" / "gone", target_is_directory=True)

    assert (controller / "subsystem").is_symlink()
    assert not (controller / "subsystem").exists()
    assert _backing(sysfs) is DeviceBacking.UNKNOWN


def test_a_stack_whose_layer_link_dangles_is_unknown(tmp_path: Path) -> None:
    """The same shape one level up, where dropping the layer is the tempting mistake.

    A ``slaves`` entry that does not resolve to a directory is a layer of the stack that
    could not be read. Skipping it would decide the stack over the layers that *were*
    readable — so a mirror of a local disk and a dangling link to an iSCSI LUN would
    come back ``LOCAL``, which is ADR-0230 §6's "over the whole backing chain" answered
    over part of it.
    """
    sysfs = Sysfs(tmp_path)
    _stack(sysfs, transports=["pcie"])
    slaves = sysfs.root / "devices" / "virtual" / "block" / "dm-0" / "slaves"
    (slaves / "gone").symlink_to(sysfs.root / "devices" / "nowhere", target_is_directory=True)

    assert _backing(sysfs) is DeviceBacking.UNKNOWN
