import sys
from celeste_timer import fmt_time
from full_splits import main

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


def render_stream(sm):
    split_cur_chapter = sm.current_split(0)
    split_cur_segment = sm.current_split(1)
    split_prev_chapter = sm.previous_split(0)
    split_prev_segment = sm.previous_split(1)
    if not any(subseg == (split_cur_segment, 1) for subseg in sm.route.all_subsegments):
        split_cur_segment = None
    if not any(subseg == (split_prev_segment, 1) for subseg in sm.route.all_subsegments):
        split_prev_segment = None

    stats_cur_chapter = generate_stats(sm, split_cur_chapter, 0)
    stats_cur_segment = generate_stats(sm, split_cur_segment, 1)
    stats_prev_chapter = generate_stats(sm, split_prev_chapter, 0)
    stats_prev_segment = generate_stats(sm, split_prev_segment, 1)

    result = []

    result.append(sm.route.name)
    result.append('')

    s = stats_prev_chapter if split_prev_segment is None else stats_prev_segment
    result.append('Timer: %s%s' % (
        NORMAL if not sm.done else GREEN if s['pb_diff'] is None else color_mark(s),
        fmt_time_ex(sm.current_time, True),
    ))
    result.append('%s PB by %s%s%s' % (
        'Ahead of' if s['pb_diff'] is None or s['pb_diff'] < 0 else 'Behind',
        color_mark(s),
        fmt_time_ex(s['pb_diff'], split_cur_segment),
        NORMAL,
    ))
    #result.append('Could maybe get: %s' % fmt_time_ex(sm.best_possible_time(), True))
    result.append('')

    result.append('%s: %s%s%s/%s' % (
        sm.route.level_names[0],
        color_split(stats_cur_chapter),
        fmt_time_ex(stats_cur_chapter["atime"], split_cur_chapter),
        NORMAL,
        fmt_time_ex(stats_cur_chapter["ptime"], split_cur_chapter)
    ))
    result.append('Can save: %s' % fmt_time_ex(stats_cur_chapter['possible_timesave'], split_cur_chapter))
    result.append('')

    result.append('%s: %s%s%s/%s' % (
        sm.route.level_names[1],
        color_split(stats_cur_segment),
        fmt_time_ex(stats_cur_segment["atime"], split_cur_segment),
        NORMAL,
        fmt_time_ex(stats_cur_segment["ptime"], split_cur_segment)
    ))
    result.append('Can save: %s' % fmt_time_ex(stats_cur_segment['possible_timesave'], split_cur_segment))
    result.append('')


    result.append('Prev. %s:\nCould save %s\n%s %s%s%s%s\n' % (
        sm.route.level_names[0],
        fmt_time_ex(stats_prev_chapter['possible_timesave'], split_prev_chapter),
        'Saved' if stats_prev_chapter['pb_delta'] is None or stats_prev_chapter['pb_delta'] < 0 else 'Lost',
        color_split(stats_prev_chapter),
        fmt_time_ex(stats_prev_chapter['pb_delta'], split_prev_chapter),
        NORMAL,
        ' (!!!)' if stats_prev_chapter['gold'] else '',
    ))
    result.append('Prev. %s:\nCould save %s\n%s %s%s%s%s' % (
        sm.route.level_names[1],
        fmt_time_ex(stats_prev_segment['possible_timesave'], split_prev_segment),
        'Saved' if stats_prev_segment['pb_delta'] is None or stats_prev_segment['pb_delta'] < 0 else 'Lost',
        color_split(stats_prev_segment),
        fmt_time_ex(stats_prev_segment['pb_delta'], split_prev_segment),
        NORMAL,
        ' (!!!)' if stats_prev_segment['gold'] else '',
    ))

    return '\n'.join(result)

if __name__ == '__main__':
    sys.stdout.write("\x1b]2;streamdisplay\x07")
    main(sys.argv[1], renderer=render_stream)
