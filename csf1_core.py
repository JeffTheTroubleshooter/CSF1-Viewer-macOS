#!/usr/bin/env python3
"""CSF1 on-disk reader/writer matching JCkernel src/fs/csf1.h + csf1.c (v6)."""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

SECTOR = 512
CSF1_MAGIC = 0x33465343  # bytes "CSF3"
CSF1_START = 4096
CSF1_V6 = 6
CSF1_ALLOC = 4
JOURNAL_V3 = 42
JOURNAL_V5 = 1 + 256
MAX_CONTENT = 262144  # 256 KiB — kernel FileEntry content cap

# packed superblock (512)
_SB_FMT = "<6I32s20sI17s10I375s"
assert struct.calcsize(_SB_FMT) == 512

# packed v6 directory entry (512)
_DE_FMT = "<256s64s20s20s32s20s6I76s"
assert struct.calcsize(_DE_FMT) == 512


def _c(s: bytes, n: int) -> str:
    if isinstance(s, str):
        s = s.encode("latin-1", "replace")
    s = s.split(b"\x00", 1)[0]
    return s.decode("utf-8", "replace")[:n]


def _b(s: str, n: int) -> bytes:
    return (s or "").encode("utf-8", "replace")[:n].ljust(n, b"\x00")


def fnv1a(data: bytes) -> int:
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Superblock:
    magic: int = 0
    version: int = 0
    file_count: int = 0
    folder_count: int = 0
    max_files: int = 0
    max_folders: int = 0
    disk_name: str = ""
    created_at: str = ""
    total_size_mb: int = 0
    layout_id: str = ""
    system_sectors: int = 0
    data_sectors: int = 0
    backup_sectors: int = 0
    cache_sectors: int = 0
    backup_count: int = 0
    bitmap_start_sector: int = 0
    bitmap_sectors: int = 0
    data_start_sector: int = 0
    free_data_sectors: int = 0
    allocation_block_sectors: int = 0
    origin_lba: int = CSF1_START  # where magic was found

    @classmethod
    def unpack(cls, raw: bytes, origin: int = CSF1_START) -> "Superblock":
        t = struct.unpack(_SB_FMT, raw[:512])
        return cls(
            magic=t[0], version=t[1], file_count=t[2], folder_count=t[3],
            max_files=t[4], max_folders=t[5],
            disk_name=_c(t[6], 31), created_at=_c(t[7], 19),
            total_size_mb=t[8], layout_id=_c(t[9], 16),
            system_sectors=t[10], data_sectors=t[11],
            backup_sectors=t[12], cache_sectors=t[13], backup_count=t[14],
            bitmap_start_sector=t[15], bitmap_sectors=t[16],
            data_start_sector=t[17], free_data_sectors=t[18],
            allocation_block_sectors=t[19], origin_lba=origin,
        )

    def pack(self) -> bytes:
        return struct.pack(
            _SB_FMT,
            self.magic, self.version, self.file_count, self.folder_count,
            self.max_files, self.max_folders,
            _b(self.disk_name, 32), _b(self.created_at, 20),
            self.total_size_mb, _b(self.layout_id, 17),
            self.system_sectors, self.data_sectors,
            self.backup_sectors, self.cache_sectors, self.backup_count,
            self.bitmap_start_sector, self.bitmap_sectors,
            self.data_start_sector, self.free_data_sectors,
            self.allocation_block_sectors, b"\x00" * 375,
        )


@dataclass
class DirEntry:
    path: str = ""
    name: str = ""
    created_at: str = ""
    modified_at: str = ""
    owner: str = "core"
    deleted_at: str = ""
    size: int = 0
    data_start_sector: int = 0
    data_sector_count: int = 0
    data_checksum: int = 0
    data_generation: int = 0
    flags: int = 0
    kind: str = "file"  # file | folder
    index: int = 0
    content: bytes = field(default_factory=bytes)

    def is_empty(self) -> bool:
        return not self.name.strip("\x00").strip()

    @classmethod
    def unpack(cls, raw: bytes, kind: str = "file", index: int = 0) -> "DirEntry":
        t = struct.unpack(_DE_FMT, raw[:512])
        return cls(
            path=_c(t[0], 255), name=_c(t[1], 63),
            created_at=_c(t[2], 19), modified_at=_c(t[3], 19),
            owner=_c(t[4], 31), deleted_at=_c(t[5], 19),
            size=t[6], data_start_sector=t[7], data_sector_count=t[8],
            data_checksum=t[9], data_generation=t[10], flags=t[11],
            kind=kind, index=index,
        )

    def pack(self) -> bytes:
        return struct.pack(
            _DE_FMT,
            _b(self.path, 256), _b(self.name, 64),
            _b(self.created_at, 20), _b(self.modified_at, 20),
            _b(self.owner, 32), _b(self.deleted_at, 20),
            self.size & 0xFFFFFFFF, self.data_start_sector,
            self.data_sector_count, self.data_checksum,
            self.data_generation, self.flags,
            b"\x00" * 76,
        )


def journal_sectors(version: int) -> int:
    if version >= 5:
        return JOURNAL_V5
    if version >= 3:
        return JOURNAL_V3
    return 0


def sectors_per_entry(version: int) -> int:
    return 1 if version >= CSF1_V6 else max(1, (MAX_CONTENT + 512 + 511) // 512)


def size_class(needed: int) -> int:
    for c in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512):
        if needed <= c:
            return c
    return needed


class BlockDev:
    """Sector device: read/write 512-byte LBAs."""

    def read_lba(self, lba: int, count: int = 1) -> bytes:
        raise NotImplementedError

    def write_lba(self, lba: int, data: bytes) -> None:
        raise NotImplementedError

    def size_bytes(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def flush(self) -> None:
        pass


class RawBlockDev(BlockDev):
    def __init__(self, path: str, writable: bool = False):
        self.path = path
        self.writable = writable
        mode = "r+b" if writable else "rb"
        try:
            self.fp = open(path, mode)
        except OSError:
            if writable:
                self.fp = open(path, "rb")
                self.writable = False
            else:
                raise
        self.fp.seek(0, os.SEEK_END)
        self._size = self.fp.tell()

    def size_bytes(self) -> int:
        return self._size

    def read_lba(self, lba: int, count: int = 1) -> bytes:
        off = lba * SECTOR
        self.fp.seek(off)
        data = self.fp.read(count * SECTOR)
        if len(data) < count * SECTOR:
            data = data + b"\x00" * (count * SECTOR - len(data))
        return data

    def write_lba(self, lba: int, data: bytes) -> None:
        if not self.writable:
            raise PermissionError("image opened read-only")
        if len(data) % SECTOR:
            data = data + b"\x00" * (SECTOR - (len(data) % SECTOR))
        self.fp.seek(lba * SECTOR)
        self.fp.write(data)
        end = (lba * SECTOR) + len(data)
        if end > self._size:
            self._size = end

    def flush(self) -> None:
        self.fp.flush()
        try:
            os.fsync(self.fp.fileno())
        except OSError:
            pass

    def close(self) -> None:
        try:
            self.fp.close()
        except OSError:
            pass


class CSF1Volume:
    def __init__(self, dev: BlockDev):
        self.dev = dev
        self.sb: Optional[Superblock] = None
        self.files: List[DirEntry] = []
        self.folders: List[DirEntry] = []
        self.bitmap = bytearray()
        self.detected = False
        self.message = ""

    def inspect(self) -> str:
        """Read LBA 4096 only. Off-sector CSF3 (kernel payload) is not a volume.

        Returns one of: NO_SUPERBLOCK | WRONG_MAGIC | WRONG_VERSION | MOUNT_OK
        """
        raw = self.dev.read_lba(CSF1_START, 1)
        if raw == b"\x00" * SECTOR:
            self.message = "NO_SUPERBLOCK"
            return "NO_SUPERBLOCK"
        magic = struct.unpack_from("<I", raw)[0]
        if magic != CSF1_MAGIC:
            self.message = "WRONG_MAGIC"
            return "WRONG_MAGIC"
        version = struct.unpack_from("<I", raw, 4)[0]
        if version != CSF1_V6:
            self.message = "WRONG_VERSION"
            return "WRONG_VERSION"
        self.message = "MOUNT_OK"
        return "MOUNT_OK"

    def detect_and_mount(self) -> bool:
        # Inspect path / GUI mount: LBA 4096 only. Do not scan first 64 MiB.
        token = self.inspect()
        if token != "MOUNT_OK":
            self.detected = False
            return False
        try:
            if self._mount_at(CSF1_START):
                self.detected = True
                self.message = (
                    f"CSF1 detected at LBA {CSF1_START} "
                    f"(v{self.sb.version}, disk '{self.sb.disk_name}', "
                    f"{self.sb.file_count} files / {self.sb.folder_count} folders, "
                    f"{self.sb.total_size_mb} MB)"
                )
                return True
        except Exception as e:
            self.message = str(e)
            self.detected = False
            return False
        self.detected = False
        return False

    def _mount_at(self, origin: int) -> bool:
        raw = self.dev.read_lba(origin, 1)
        sb = Superblock.unpack(raw, origin)
        if sb.magic != CSF1_MAGIC:
            return False
        if sb.max_files == 0 or sb.max_files > 2500:
            return False
        if sb.max_folders == 0 or sb.max_folders > 2500:
            return False
        self.sb = sb
        spe = sectors_per_entry(sb.version)
        jrn = journal_sectors(sb.version)
        # metadata start after super + journal + bitmap
        meta = origin + 1 + jrn + (sb.bitmap_sectors if sb.version >= CSF1_ALLOC else 0)
        if sb.bitmap_start_sector:
            bstart = sb.bitmap_start_sector
        else:
            bstart = origin + 1 + jrn
        if sb.bitmap_sectors and sb.version >= CSF1_ALLOC:
            self.bitmap = bytearray(self.dev.read_lba(bstart, sb.bitmap_sectors))
        else:
            self.bitmap = bytearray()

        self.files = []
        for i in range(sb.max_files):
            raw_e = self.dev.read_lba(meta + i * spe, spe)
            if sb.version >= CSF1_V6:
                e = DirEntry.unpack(raw_e[:512], "file", i)
            else:
                # legacy: name/path at start of huge FileEntry
                e = DirEntry.unpack(raw_e[:512], "file", i)
            if i < sb.file_count and not e.is_empty():
                if e.size and e.data_sector_count and sb.version >= CSF1_V6:
                    e.content = self._read_data(e)
                elif sb.version < CSF1_V6 and e.size:
                    # content follows metadata in legacy blob; skip huge parse
                    e.content = raw_e[512:512 + min(e.size, MAX_CONTENT)]
                self.files.append(e)

        fbase = meta + sb.max_files * spe
        self.folders = []
        for i in range(sb.max_folders):
            raw_e = self.dev.read_lba(fbase + i * spe, spe)
            e = DirEntry.unpack(raw_e[:512], "folder", i)
            if i < sb.folder_count and not e.is_empty():
                self.folders.append(e)
        return True

    def _read_data(self, e: DirEntry) -> bytes:
        if not e.size or not e.data_sector_count:
            return b""
        need = (e.size + SECTOR - 1) // SECTOR
        need = min(need, e.data_sector_count)
        raw = self.dev.read_lba(self.sb.data_start_sector + e.data_start_sector, need)
        data = raw[: e.size]
        return data

    def _bit_get(self, rel: int) -> int:
        byte, bit = divmod(rel, 8)
        if byte >= len(self.bitmap):
            return 1
        return (self.bitmap[byte] >> bit) & 1

    def _bit_set(self, rel: int, val: int) -> None:
        byte, bit = divmod(rel, 8)
        if byte >= len(self.bitmap):
            self.bitmap.extend(b"\x00" * (byte + 1 - len(self.bitmap)))
        if val:
            self.bitmap[byte] |= (1 << bit)
        else:
            self.bitmap[byte] &= ~(1 << bit)

    def _alloc(self, need: int) -> int:
        need = size_class(need)
        limit = self.sb.data_sectors or (len(self.bitmap) * 8)
        run = 0
        start = 0
        for i in range(limit):
            if self._bit_get(i) == 0:
                if run == 0:
                    start = i
                run += 1
                if run >= need:
                    for j in range(start, start + need):
                        self._bit_set(j, 1)
                    return start
            else:
                run = 0
        raise OSError("CSF1 data region is full")

    def _free_extent(self, start: int, count: int) -> None:
        for i in range(start, start + count):
            self._bit_set(i, 0)

    def _write_bitmap(self) -> None:
        if not self.sb.bitmap_sectors:
            return
        data = bytes(self.bitmap[: self.sb.bitmap_sectors * SECTOR])
        if len(data) < self.sb.bitmap_sectors * SECTOR:
            data = data.ljust(self.sb.bitmap_sectors * SECTOR, b"\x00")
        self.dev.write_lba(self.sb.bitmap_start_sector, data)

    def _write_sb(self) -> None:
        self.dev.write_lba(self.sb.origin_lba, self.sb.pack())

    def _write_entry(self, e: DirEntry) -> None:
        spe = sectors_per_entry(self.sb.version)
        jrn = journal_sectors(self.sb.version)
        meta = self.sb.origin_lba + 1 + jrn + (
            self.sb.bitmap_sectors if self.sb.version >= CSF1_ALLOC else 0
        )
        if e.kind == "folder":
            lba = meta + self.sb.max_files * spe + e.index * spe
        else:
            lba = meta + e.index * spe
        blob = e.pack()
        if spe > 1:
            blob = blob.ljust(spe * SECTOR, b"\x00")
        self.dev.write_lba(lba, blob)

    def add_file(self, host_path: str, dest_dir: str = "/Base/Files") -> DirEntry:
        if not getattr(self.dev, "writable", False):
            raise PermissionError("volume opened read-only")
        if not self.sb:
            raise RuntimeError("volume not mounted")
        with open(host_path, "rb") as f:
            data = f.read(MAX_CONTENT + 1)
        if len(data) > MAX_CONTENT:
            data = data[:MAX_CONTENT]
        name = os.path.basename(host_path)[:63] or "imported.bin"
        dest_dir = dest_dir.rstrip("/") or "/Base/Files"
        used = {e.index for e in self.files}
        idx = None
        for i in range(self.sb.max_files):
            if i not in used:
                idx = i
                break
        if idx is None:
            raise OSError("no free CSF1 file slot")
        need = (len(data) + SECTOR - 1) // SECTOR if data else 0
        rel = 0
        count = 0
        if need:
            count = size_class(need)
            rel = self._alloc(count)
            payload = data.ljust(count * SECTOR, b"\x00")
            self.dev.write_lba(self.sb.data_start_sector + rel, payload)
        stamp = now_stamp()
        e = DirEntry(
            path=dest_dir[:255],
            name=name,
            created_at=stamp,
            modified_at=stamp,
            owner="core",
            size=len(data),
            data_start_sector=rel,
            data_sector_count=count,
            data_checksum=fnv1a(data),
            data_generation=1,
            flags=1 if data else 0,
            kind="file",
            index=idx,
            content=data,
        )
        self._write_entry(e)
        self.files.append(e)
        self.sb.file_count = max(self.sb.file_count, len(self.files))
        if self.sb.free_data_sectors >= count:
            self.sb.free_data_sectors -= count
        self._write_bitmap()
        self._write_sb()
        self.dev.flush()
        return e

    def remove_file(self, index: int) -> None:
        if not getattr(self.dev, "writable", False):
            raise PermissionError("volume opened read-only")
        victim = None
        for e in self.files:
            if e.index == index:
                victim = e
                break
        if not victim:
            raise KeyError("file index not found")
        if victim.data_sector_count:
            self._free_extent(victim.data_start_sector, victim.data_sector_count)
        empty = DirEntry(kind="file", index=index)
        self._write_entry(empty)
        self.files = [e for e in self.files if e.index != index]
        self.sb.file_count = len(self.files)
        self._write_bitmap()
        self._write_sb()
        self.dev.flush()

    def export_file(self, index: int, host_path: str) -> None:
        if not getattr(self.dev, "writable", False):
            raise PermissionError("volume opened read-only")
        for e in self.files:
            if e.index == index:
                with open(host_path, "wb") as f:
                    f.write(e.content)
                return
        raise KeyError("file index not found")

    def tree_rows(self, order: str = "az") -> List[Tuple[str, DirEntry]]:
        rows: List[Tuple[str, DirEntry]] = []
        for e in self.folders:
            p = (e.path.rstrip("/") + "/" + e.name) if e.path else ("/" + e.name)
            rows.append((p.replace("//", "/"), e))
        for e in self.files:
            p = (e.path.rstrip("/") + "/" + e.name) if e.path else ("/" + e.name)
            rows.append((p.replace("//", "/"), e))
        reverse = order.lower() in ("za", "high-low", "high_to_low", "desc")
        rows.sort(key=lambda r: r[0].lower(), reverse=reverse)
        return rows
