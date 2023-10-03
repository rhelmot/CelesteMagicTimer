#!/usr/bin/env python3

from celeste_timer import AutoSplitterInfo
import time
import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser(
        prog='Celeste Events Trigger',
        description='Trigger commands on specific events',
    )
    parser.add_argument('--dump', type=str,
        default='/dev/shm/autosplitterinfo',
        help='The autosplitterinfo file path (default: /dev/shm/autosplitterinfo)'
    )

    parser.add_argument('--level-start', type=str,
        help='The command triggered on level start'
    )
    parser.add_argument('--level-end', type=str,
        help='The command triggered on level end'
    )

    args = parser.parse_args()

    info = AutoSplitterInfo(args.dump)

    attrs = info.dict
    prev_attrs = attrs

    while True:
        time.sleep(0.05)
        attrs = info.dict

        if args.level_start and prev_attrs['level_name'] == "" and attrs['level_name'] != "":
            subprocess.run(['/bin/sh', '-c', args.level_start])
        if args.level_end and attrs['level_name'] == "" and prev_attrs['level_name'] != "":
            subprocess.run(['/bin/sh', '-c', args.level_end])

        prev_attrs = attrs

if __name__ == '__main__':
    main()
