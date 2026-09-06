#!/usr/bin/env python3
"""Minimal QCOW2 v2/v3 reader with write-through on already-allocated clusters.

Full cluster allocation on write is supported for uncompressed images.
Compressed clusters stay read-only.
"""

from __future__ import annotations

import os
import struct
from typing import Dict, Optional

from csf1_core import SECTOR, BlockDev

QCOW_MAGIC = 0x514649FB
QCOW2_OFLAG_COPIED = 1 << 63
QCOW2_OFLAG_COMPRESSED = 1 << 62
QCOW2_OFLAG_ZERO = 1 << 0  # v3 L2
L2_OFFSET_MASK = (1 << 62) - 1


class Qcow2BlockDev(BlockDev):
    def __init__(self, path: str, writable: bool = False):
        self.path = path
        self.writable = writable
        mode = "r+b" if writable else "rb"
        try:
            self.fp = open(path, mode)
        except OSError:
            self.fp = open(path, "rb")
            self.writable = False
        hdr = self.fp.read(104)
        if len(hdr) < 72:
            raise ValueError("not a qcow2 file")
        magic, version = struct.unpack_from(">II", hdr, 0)
        if magic != QCOW_MAGIC:
            raise ValueError("not a qcow2 file (bad magic)")
        if version not in (2, 3):
            raise ValueError(f"unsupported qcow2 version {version}")
        self.version = version
        (
            _bk_off,
            _bk_sz,
            cluster_bits,
            virtual_size,
            crypt,
            l1_size,
            l1_off,
            _refcount_off,
            _refcount_clusters,
            nb_snaps,
            snap_off,
        ) = struct.unpack_from(">QIIQIIQQIIQ", hdr, 8)  # backing u64, backing_sz u32, cluster_bits u32, size u64, crypt u32, l1_size u32, l1_off u64, ...
        if crypt:
            raise ValueError("encrypted qcow2 is not supported")
        self.cluster_bits = cluster_bits
        self.cluster_size = 1 << cluster_bits
        self.virtual_size = virtual_size
        self.l1_size = l1_size
        self.l1_off = l1_off
        self.l2_entries = self.cluster_size // 8
        self.fp.seek(l1_off)
        raw = self.fp.read(l1_size * 8)
        self.l1 = list(struct.unpack(">" + "Q" * l1_size, raw.ljust(l1_size * 8, b"\x00")))
        self._l2_cache: Dict[int, list] = {}

    def size_bytes(self) -> int:
        return self.virtual_size

    def _l2(self, l1_index: int) -> Optional[list]:
        off = self.l1[l1_index] & L2_OFFSET_MASK
        if not off:
            return None
        if off in self._l2_cache:
            return self._l2_cache[off]
        self.fp.seek(off)
        raw = self.fp.read(self.cluster_size)
        n = self.l2_entries
        tbl = list(struct.unpack(">" + "Q" * n, raw[: n * 8]))
        self._l2_cache[off] = tbl
        return tbl

    def _cluster_host(self, guest_off: int) -> tuple:
        """Return (host_offset or 0, zero, compressed)."""
        cidx = guest_off // self.cluster_size
        l2i = cidx % self.l2_entries
        l1i = cidx // self.l2_entries
        if l1i >= self.l1_size:
            return 0, True, False
        tbl = self._l2(l1i)
        if not tbl:
            return 0, True, False
        ent = tbl[l2i]
        if ent & QCOW2_OFLAG_COMPRESSED:
            return 0, False, True
        host = ent & L2_OFFSET_MASK
        zero = (self.version >= 3 and (ent & QCOW2_OFLAG_ZERO)) or host == 0
        return host, zero, False

    def read_lba(self, lba: int, count: int = 1) -> bytes:
        out = bytearray()
        need = count * SECTOR
        g = lba * SECTOR
        while len(out) < need:
            host, zero, comp = self._cluster_host(g)
            inside = g % self.cluster_size
            take = min(self.cluster_size - inside, need - len(out))
            if comp:
                raise ValueError("compressed qcow2 cluster — convert with qemu-img first")
            if zero or not host:
                out.extend(b"\x00" * take)
            else:
                self.fp.seek(host + inside)
                chunk = self.fp.read(take)
                if len(chunk) < take:
                    chunk += b"\x00" * (take - len(chunk))
                out.extend(chunk)
            g += take
        return bytes(out)

    def _file_size(self) -> int:
        self.fp.seek(0, os.SEEK_END)
        return self.fp.tell()

    def _align_up(self, n: int) -> int:
        cs = self.cluster_size
        return (n + cs - 1) // cs * cs

    def _alloc_cluster(self) -> int:
        if not self.writable:
            raise PermissionError("qcow2 opened read-only")
        end = self._align_up(self._file_size())
        self.fp.seek(end)
        self.fp.write(b"\x00" * self.cluster_size)
        return end

    def _ensure_l2(self, l1_index: int) -> list:
        off = self.l1[l1_index] & L2_OFFSET_MASK
        if off:
            return self._l2(l1_index)  # type: ignore
        off = self._alloc_cluster()
        self.l1[l1_index] = off | QCOW2_OFLAG_COPIED
        self.fp.seek(self.l1_off + l1_index * 8)
        self.fp.write(struct.pack(">Q", self.l1[l1_index]))
        tbl = [0] * self.l2_entries
        self._l2_cache[off] = tbl
        return tbl

    def write_lba(self, lba: int, data: bytes) -> None:
        if not self.writable:
            raise PermissionError("qcow2 opened read-only")
        if len(data) % SECTOR:
            data = data + b"\x00" * (SECTOR - (len(data) % SECTOR))
        g = lba * SECTOR
        pos = 0
        while pos < len(data):
            host, zero, comp = self._cluster_host(g)
            if comp:
                raise ValueError("cannot write compressed qcow2 cluster")
            inside = g % self.cluster_size
            take = min(self.cluster_size - inside, len(data) - pos)
            if not host:
                cidx = g // self.cluster_size
                l2i = cidx % self.l2_entries
                l1i = cidx // self.l2_entries
                tbl = self._ensure_l2(l1i)
                host = self._alloc_cluster()
                tbl[l2i] = host | QCOW2_OFLAG_COPIED
                l2off = self.l1[l1i] & L2_OFFSET_MASK
                self.fp.seek(l2off + l2i * 8)
                self.fp.write(struct.pack(">Q", tbl[l2i]))
            self.fp.seek(host + inside)
            self.fp.write(data[pos : pos + take])
            g += take
            pos += take

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


def open_disk(path: str, writable: bool = False) -> BlockDev:
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == b"QFI\xfb":
        return Qcow2BlockDev(path, writable)
    return __import__("csf1_core").RawBlockDev(path, writable)
