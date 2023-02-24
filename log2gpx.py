#!/usr/bin/env python3

import os, sys
from dataclasses import dataclass
from typing import List

#
# This script converts GPS tracks from an Olympus camera into gpx format.
#
# The camera saves GPS tracks as NMEA sentences to a file with extension .LOG.
# File format described here: github.com/GPSBabel/gpsbabel/blob/master/nmea.cc
#

@dataclass
class TrackPoint:
    latitude : float
    longitude: float
    elevation: str
    iso_time : str

def read_log(fn: str) -> List[TrackPoint]:
    result = []
    line_no = 0
    with open(fn, 'rt') as f:
        while True:
            line = f.readline().strip()
            if len(line) == 0:
                break
            line_no += 1

            components = line.split(',')

            if len(components) < 11:
                continue

            # verify checksum

            cksum = 8
            for c in line[:line.rfind(',')]:
                cksum ^= ord(c)

            if f'*{cksum:2X}' != components[-1]:
                print(f"Checksum error: '*{cksum:2X}' vs. '{components[-1]}' "
                      f"in line {line_no}: '{line}'.", file=sys.stderr)
                continue

            # parse line

            if components[0] == '$GPGGA':
                elevation = components[9]     # elevation
                assert components[10] == 'M'  # in meters
                continue

            if components[0] != '$GPRMC':
                continue

            time, AorV, lat, NorS, lon, EorW, _, _, date = components[1:10]

            if AorV != 'A':
                print(f"Invalid line {line_no}: '{line}'.", file=sys.stderr)
                continue

            assert lat[4] == '.'
            latitude = float(lat[:2]) + float(lat[2:]) / 60
            if NorS == 'S':
                latitude = -latitude

            assert lon[5] == '.'
            longitude = float(lon[:3]) + float(lon[3:]) / 60
            if EorW == 'W':
                longitude = -longitude

            if time[-2:] == '.0':
                time = time[:-2]
            iso_time = f'20{date[4:6]}-{date[2:4]}-{date[:2]}T' \
                       f'{time[:2]}:{time[2:4]}:{time[4:]}Z'

            result.append(TrackPoint(latitude, longitude, elevation, iso_time))

    return result

def write_gpx(fn: str, track: List[TrackPoint]) -> None:
    with open(fn, 'wt') as f:
        print('<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
              file=f)
        print('<gpx version="1.1" creator="log2gpx.py https://github.com/'
              'joergmlpts/olympus-wifi" '
              'xmlns="http://www.topografix.com/GPX/1/1" '
              'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:'
              'schemaLocation="http://www.topografix.com/GPX/1/1 http://www.'
              'topografix.com/GPX/1/1/gpx.xsd">', file=f)
        print('<trk>', file=f)
        print(f'  <name>{os.path.splitext(os.path.split(fn)[1])[0]}</name>',
              file=f)
        print('  <trkseg>', file=f)

        for point in track:
            print(f'    <trkpt lat="{point.latitude:.6f}" '
                  f'lon="{point.longitude:.6f}">', file=f)
            print(f'      <ele>{point.elevation}</ele>', file=f)
            print(f'      <time>{point.iso_time}</time>', file=f)
            print('    </trkpt>', file=f)

        print('  </trkseg>', file=f)
        print('</trk>', file=f)
        print('</gpx>', file=f)


if __name__ == '__main__':
    import argparse

    def fileName(fn):
        try:
            with open(fn, 'r') as f:
                return fn
        except:
            pass
        raise argparse.ArgumentTypeError(f"File '{fn}' cannot be read.")

    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=fileName, nargs='+',
                        help="Convert a GPS track from .LOG to .gpx format.")
    args = parser.parse_args()

    for fn in args.log:
        track = read_log(fn)
        if len(track) == 0:
            print(f"No GPS track found in '{fn}'.", file=sys.stderr)
        else:
            outfn = os.path.splitext(fn)[0] + '.gpx'
            print(f"Converting '{fn} to '{outfn}'.")
            write_gpx(outfn, track)
