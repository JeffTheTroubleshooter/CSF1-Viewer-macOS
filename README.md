# CSF1 Viewer — macOS

> **WARNING — EXPERIMENTAL SOFTWARE**
>
> Unfinished prototype. Format / Install can erase a disk.

Public host tool for JCkernel CSF1 disks. Sister editions: Linux and Windows.

Public `CSF1-Viewer-macOS` 0.3.7 launchers expect these host tools next to `CSF1-Viewer.command` / `CSF1-Viewer.sh`. A fresh clone needs `csf1_core.py`, `csf1_viewer.py`, and `qcow2io.py` on `main` (inspect-rb trio only — not the JCKernel).

| file | role |
| --- | --- |
| `csf1_core.py` | CSF1 volume inspect (rb) |
| `csf1_viewer.py` | UI / `--inspect` CLI |
| `qcow2io.py` | qcow2 reader (`>QIIQIIQQIIQ`, default read-only) |

**Not included:** `jck_install.py` (yanked; host-stamp), `host_usb.py`, any kernel sources.

`JCKERNEL_VERSION` for this public edition tracks private tip **0.0.258**.
`VIEWER_VERSION` stays **0.3.7**.

Guest FORMAT remains in-kernel `csf1_format(1)` on disk 1 — this viewer does not format volumes.

## Drag and drop (v0.3.7)

Mount the USB, then drop files or a folder onto the Viewer. Dest path default `/Base/Files`. 256 KiB per file cap.
