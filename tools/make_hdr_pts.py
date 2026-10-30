#!/usr/bin/env python3
"""Build a PTGui HDR project for one Gear 360 bracket from an already-aligned project (e.g. charuco_pooled.pts).

The template's two image groups are the two lenses (each DNG is the whole dual-fisheye frame; the crop centre picks
the lens). Every bracket frame is added to both groups, so each group is one bracketed stack (PTGui HDR linking).
Lens, lens-2 rotation, crops and settings are kept from the template, so the bracket needs no aligning.
Exposure time, aperture and ISO for each frame are read from the DNG's EXIF (tools/raw2dng.py copies them from the
camera JPEG), so PTGui knows how the frames relate. Control points are kept (they are the calibration's; they only
matter if the project is optimised again).

Usage:
  python3 tools/make_hdr_pts.py captures/2026-10-12-hdr-1/360_039[1-5].dng \\
      --template captures/2026-10-12-charuco/charuco_pooled.pts --out "captures/2026-10-12-hdr-1/360_0391 HDR.pts"
"""
import argparse
import copy
import json
import os
import subprocess
import sys


def exif(paths):
    r = subprocess.run(['exiftool', '-j', '-n', '-ExposureTime', '-FNumber', '-ISO', '-Make', '-Model'] + paths,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'exiftool failed: {r.stderr.strip()}')
    return {os.path.abspath(d['SourceFile']): d for d in json.loads(r.stdout)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dngs', nargs='+', help='bracket frames (DNG from tools/raw2dng.py), all in one folder')
    ap.add_argument('--template', required=True, help='aligned PTGui project with 2 image groups (one per lens)')
    ap.add_argument('--out', required=True, help='project to write, in the same folder as the DNGs')
    args = ap.parse_args()

    out_dir = os.path.dirname(os.path.abspath(args.out))
    dngs = [os.path.abspath(p) for p in args.dngs]
    for p in dngs:
        if os.path.dirname(p) != out_dir:
            sys.exit(f'{p} is not in the output folder {out_dir}; PTGui paths are written relative to the project')
    meta = exif(dngs)
    missing = [os.path.basename(p) for p in dngs if 'ExposureTime' not in meta[p]]
    if missing:
        sys.exit(f'no ExposureTime EXIF in {missing}: re-run tools/raw2dng.py (it copies EXIF from the camera JPEG)')
    dngs.sort(key=lambda p: -float(meta[p]['ExposureTime']))     # longest exposure first

    proj = json.load(open(args.template, encoding='utf-8'))
    p = proj['project']
    if len(p['imagegroups']) != 2:
        sys.exit(f'template has {len(p["imagegroups"])} image groups, expected 2 (one per lens)')
    for g in p['imagegroups']:
        proto = g['images'][0]
        g['images'] = []
        for path in dngs:
            m = meta[path]
            st = os.stat(path)
            im = copy.deepcopy(proto)
            im['filename'] = os.path.basename(path)
            md = im['metadata']
            md['exposuretime'] = float(m['ExposureTime'])
            md['aperture'] = float(m['FNumber']) if 'FNumber' in m else md.get('aperture')
            md['iso'] = float(m['ISO']) if 'ISO' in m else md.get('iso')
            md['filesize'] = st.st_size
            md['filetimestamp'] = int(st.st_mtime)
            md['exposurebias'] = 0
            if isinstance(im.get('photometric'), dict):
                im['photometric']['exposureoffset'] = 0
            g['images'].append(im)
    p['projectsettings']['hdrsettings']['hdrlinkmode'] = 'hdrlink'
    p['outputcomponents']['hdrblended'] = True
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(proj, f, indent='\t')
    print(f'template {args.template}: lens-2 yaw/pitch/roll '
          + ', '.join(f'{p["imagegroups"][1]["position"]["params"][k]:+.4f}' for k in ('yaw', 'pitch', 'roll')))
    for path in dngs:
        m = meta[path]
        t = float(m['ExposureTime'])
        print(f'  {os.path.basename(path)}: {"1/%d" % round(1 / t) if t < 1 else "%g" % t} s, ISO {m.get("ISO")}, '
              f'f/{m.get("FNumber")}  ({m.get("Make")} {m.get("Model")})')
    print(f'{len(dngs)} frames x 2 lenses = {2 * len(dngs)} images, HDR-linked; wrote {args.out}')


if __name__ == '__main__':
    main()
