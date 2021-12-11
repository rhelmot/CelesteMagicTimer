#!/usr/bin/env python3

import sys
import functools
from celeste_timer import fmt_time
from full_splits import main, print_splits

def fmt_time_ex(time, meaningful, sign=False):
    if meaningful is None:
        return '----'
    elif time is None:
        return '??.?'
    elif time < 60 * 1000:
        return fmt_time(time, ms_decimals=1, sign=sign)
    else:
        return fmt_time(time, ms_decimals=0, sign=sign)

RED = '\x1b[31m'
GREEN = '\x1b[32m'
GOLD = '\x1b[33m'
NORMAL = '\x1b[0m'

def color_split(stats):
    if stats['atime'] is None:
        return NORMAL
    elif stats['status'] == 'past' and stats['gtime'] is not None and stats['atime'] < stats['gtime']:
        return GOLD
    elif stats['ptime'] is None:
        return NORMAL
    elif stats['atime'] > stats['ptime']:
        return RED
    else:
        return GREEN

def color_mark(stats):
    if stats['pb_diff'] is None:
        return NORMAL
    elif stats['pb_diff'] < 0:
        return GREEN
    else:
        return RED

def generate_stats(sm, split, level):
    if split is not None:
        if sm.current_split(level) is split:
            status = 'present'
            atime = sm.current_segment_time(level)
            amark = sm.current_time
        elif sm.is_segment_done(split):
            status = 'past'
            atime = sm.current_times.segment_time(split, level)
            amark = sm.current_times[split]
        else:
            status = 'future'
            atime = None
            amark = None

        ptime = sm.compare_pb.segment_time(split, level)
        gtime = sm.compare_best[(split, level)]
        possible_timesave = ptime - gtime if ptime is not None and gtime is not None else None
        pb_delta = atime - ptime if atime is not None and ptime is not None else None
        gold = atime < gtime if atime is not None and gtime is not None else False

        pmark = sm.compare_pb[split]
        pb_diff = amark - pmark if amark is not None and pmark is not None else None
    else:
        status = None
        atime = None
        ptime = None
        gtime = None
        possible_timesave = None
        pb_delta = None
        gold = False
        amark = None
        pmark = None
        pb_diff = None

    return {
        'status': status,
        'atime': atime,
        'ptime': ptime,
        'gtime': gtime,
        'possible_timesave': possible_timesave,
        'pb_delta': pb_delta,
        'gold': gold,
        'amark': amark,
        'pmark': pmark,
        'pb_diff': pb_diff,
    }


def format_stream(sm):
    num_levels = max(1, len(sm.route.level_names))
    splits_cur = [sm.current_split(i) for i in range(num_levels)]
    splits_prev = [sm.previous_split(i) for i in range(num_levels)]
    for lvl in range(1, num_levels):
        if not any(subseg == (splits_cur[lvl], lvl) for subseg in sm.route.all_subsegments):
            splits_cur[lvl] = None
        if not any(subseg == (splits_prev[lvl], lvl) for subseg in sm.route.all_subsegments):
            splits_prev[lvl] = None

    stats_cur = [generate_stats(sm, splits_cur[lvl], lvl) for lvl in range(num_levels)]
    stats_prev = [generate_stats(sm, splits_prev[lvl], lvl) for lvl in range(num_levels)]

    result = []

    result.append(sm.route.name)
    result.append('')

    for split, stat in zip(splits_prev, stats_prev):
        if split is not None or split is splits_prev[0]:
            s = stat
            sp = split
    result.append('Timer: %s%s' % (
        NORMAL if not sm.done else GREEN if s['pb_diff'] is None else color_mark(s),
        fmt_time_ex(sm.current_time, True),
    ))
    result.append('%s PB by %s%s%s' % (
        'Ahead of' if s['pb_diff'] is None or s['pb_diff'] < 0 else 'Behind',
        color_mark(s),
        fmt_time_ex(s['pb_diff'], sp),
        NORMAL,
    ))
    #result.append('Could maybe get: %s' % fmt_time_ex(sm.best_possible_time(), True))
    result.append('')

    for name, split, stat in zip(sm.route.level_names, splits_cur, stats_cur):
        result.append('%s: %s%s%s/%s' % (
            name,
            color_split(stat),
            fmt_time_ex(stat["atime"], split),
            NORMAL,
            fmt_time_ex(stat["ptime"], split)
        ))
        result.append('Can save: %s' % fmt_time_ex(stat['possible_timesave'], split))
        result.append('')

    for name, split, stat in zip(sm.route.level_names, splits_prev, stats_prev):
        result.append('Prev. %s:\nCould save %s\n%s %s%s%s%s\n' % (
            name,
            fmt_time_ex(stat['possible_timesave'], split),
            'Saved' if stat['pb_delta'] is None or stat['pb_delta'] < 0 else 'Lost',
            color_split(stat),
            fmt_time_ex(stat['pb_delta'], split),
            NORMAL,
            ' (!!!)' if stat['gold'] else '',
        ))

    return '\n'.join(result)

if __name__ == '__main__':
    sys.stdout.write("\x1b]2;streamdisplay\x07")
    if len(sys.argv) == 1:
        print("Please make sure to specify your route file as a command line argument!")
        sys.exit(1)
    else:
        main(sys.argv[1], renderer=functools.partial(print_splits, formatter=format_stream))
