# -*- coding: utf-8 -*-
"""Extract all user string literals (#US heap) from .NET assemblies."""
import struct, sys, json, os

def rva_to_off(sections, rva):
    for va, vsize, raw, rsize in sections:
        if va <= rva < va + max(vsize, rsize):
            return raw + (rva - va)
    return None

def read_compressed_uint(b, i):
    b0 = b[i]
    if b0 & 0x80 == 0:
        return b0, i + 1
    if b0 & 0xC0 == 0x80:
        return ((b0 & 0x3F) << 8) | b[i+1], i + 2
    return ((b0 & 0x1F) << 24) | (b[i+1] << 16) | (b[i+2] << 8) | b[i+3], i + 4

def extract(path):
    d = open(path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    assert d[pe:pe+4] == b"PE\0\0", "not a PE"
    coff = pe + 4
    nsect = struct.unpack_from("<H", d, coff + 2)[0]
    opt_size = struct.unpack_from("<H", d, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", d, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    sect = opt + opt_size
    sections = []
    for i in range(nsect):
        o = sect + i * 40
        vsize, va, rsize, raw = struct.unpack_from("<IIII", d, o + 8)
        sections.append((va, vsize, raw, rsize))
    cli_rva, cli_size = struct.unpack_from("<II", d, dd + 14 * 8)
    if not cli_rva:
        return []
    cli = rva_to_off(sections, cli_rva)
    md_rva, md_size = struct.unpack_from("<II", d, cli + 8)
    md = rva_to_off(sections, md_rva)
    assert struct.unpack_from("<I", d, md)[0] == 0x424A5342, "bad metadata sig"
    vlen = struct.unpack_from("<I", d, md + 12)[0]
    p = md + 16 + vlen
    p += 2  # flags
    nstreams = struct.unpack_from("<H", d, p)[0]; p += 2
    streams = {}
    for _ in range(nstreams):
        off, size = struct.unpack_from("<II", d, p); p += 8
        end = d.index(b"\0", p)
        name = d[p:end].decode("ascii")
        p = end + 1
        p = (p + 3) & ~3
        streams[name] = (md + off, size)
    if "#US" not in streams:
        return []
    so, ss = streams["#US"]
    blob = d[so:so + ss]
    out, i = [], 1
    while i < len(blob):
        try:
            ln, i = read_compressed_uint(blob, i)
        except IndexError:
            break
        if ln == 0:
            continue
        chunk = blob[i:i + ln]
        i += ln
        try:
            s = chunk[:-1].decode("utf-16-le")
        except Exception:
            continue
        if s:
            out.append(s)
    return out

if __name__ == "__main__":
    managed = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    result = {}
    for dll in ("Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll"):
        f = os.path.join(managed, dll)
        if os.path.exists(f):
            strs = extract(f)
            # preserve order, dedupe
            seen, uniq = set(), []
            for s in strs:
                if s not in seen:
                    seen.add(s); uniq.append(s)
            result[dll] = uniq
            print(f"{dll}: {len(strs)} literals, {len(uniq)} unique")
    with open(os.path.join(outdir, "03_code_strings.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
