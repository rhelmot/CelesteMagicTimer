#!/usr/bin/env python3

from celeste_timer import * # pylint: disable=wildcard-import,unused-wildcard-import

import os
import time
import functools
import gi
import subprocess
import yaml
gi.require_version('Notify', '0.7')
from gi.repository import Notify
Notify.init("celeste_timer")
berry = os.path.join(os.path.dirname(__file__), 'Celeste.png')
n = Notify.Notification.new('', '', berry)
n.set_urgency(2)
cancel_show_at = None
def notify(title, body, timeout):
    n.update(title, body, berry)
    n.show()
    global cancel_show_at
    cancel_show_at = time.time() + timeout

notify_level = int(os.environ.get('NOTIFY_SPLIT_LEVEL', 0))

import pynput
action_queue = []
ctrled = shifted = False
def should_handle_key():
    try:
        res = subprocess.check_output(['xdotool', 'getactivewindow', 'getwindowname']).strip().decode()
    except subprocess.CalledProcessError:
        return False
    return res in ('Celeste', 'streamdisplay')

def handle_key(key):
    global ctrled, shifted
    if key == pynput.keyboard.Key.ctrl:
        ctrled = True
    elif key == pynput.keyboard.Key.shift:
        shifted = True
    elif should_handle_key():
        if key == pynput.keyboard.KeyCode(char='\\'):
            action_queue.append('skip')
        elif key == pynput.keyboard.Key.backspace:
            if ctrled:
                action_queue.append('reset')
            elif shifted:
                action_queue.append('rewind')

def handle_release(key):
    global ctrled, shifted
    if key == pynput.keyboard.Key.ctrl:
        ctrled = False
    elif key == pynput.keyboard.Key.shift:
        shifted = False
listener = pynput.keyboard.Listener(on_press=handle_key, on_release=handle_release)

class NotifSplitsManager(SplitsManager):
    def split(self, split):
        super().split(split)
        time_top = self.current_times[split]
        comp_top = self.compare_pb[split]
        try:
            time_0 = self.current_times.segment_time(split, 0)
            comp_0 = self.compare_pb.segment_time(split, 0)
            gold_0 = self.compare_best[(split, 0)]
        except KeyError:
            time_0 = comp_0 = gold_0 = None
        try:
            time_1 = self.current_times.segment_time(split, 1)
            comp_1 = self.compare_pb.segment_time(split, 1)
            gold_1 = self.compare_best[(split, 1)]
        except KeyError:
            time_1 = comp_1 = gold_1 = None

        if comp_top is None:
            str_top = fmt_time(time_top, ms_decimals=0) + '/?'
        else:
            str_top = fmt_time(time_top, ms_decimals=0) + '/' + fmt_time(time_top - comp_top, ms_decimals=1, sign=True)

        if time_0 is None:
            str_0 = ''
        else:
            if comp_0 is None:
                str_0_a = fmt_time(time_0, ms_decimals=1)
            else:
                str_0_a = fmt_time(time_0 - comp_0, ms_decimals=1, sign=True)

            if gold_0 is None:
                str_0_b = '?'
            elif comp_0 is None:
                str_0_b = fmt_time(gold_0, ms_decimals=0, sign=False)
            else:
                str_0_b = fmt_time(comp_0 - gold_0, ms_decimals=1, sign=False)

            str_0 = str_0_a + '/' + str_0_b
            if gold_0 is not None and time_0 < gold_0:
                str_0 += ' [GOLD]'

        if time_1 is None or time_1 == time_0:
            str_1 = ''
        else:
            if comp_1 is None:
                str_1_a = fmt_time(time_1, ms_decimals=0)
            else:
                str_1_a = fmt_time(time_1 - comp_1, ms_decimals=1, sign=True)

            if gold_1 is None:
                str_1_b = '?'
            elif comp_1 is None:
                str_1_b = fmt_time(gold_1, ms_decimals=0, sign=False)
            else:
                str_1_b = fmt_time(comp_1 - gold_1, ms_decimals=1, sign=False)

            str_1 = str_1_a + '/' + str_1_b
            if gold_1 is not None and time_1 < gold_1:
                str_1 += ' [GOLD]'

        pieces = []
        if time_1 != time_0 and time_1 is not None:
            pieces.append('%s: %s' % (split.level_name(1), str_1))
        if time_0 is not None:
            pieces.append('%s: %s' % (split.level_name(0), str_0))
        pieces.append('Time: ' + str_top)
        out_str = ' == '.join(pieces)
        if split.level <= notify_level:
            notify('Split', out_str, 10)


def show_splits(route, splits):
    if type(route) is str:
        route = open_pickle_or_yaml(route)
    if type(splits) is str:
        splits = open_pickle_or_yaml(splits)
    for split in route.splits:
        stime = splits.segment_time(split, 999)
        ttime = splits[split]
        print('%20s: %s -> %s' % (split.names[-1], '--' if stime is None else fmt_time(stime, sign=True), '--' if ttime is None else fmt_time(ttime)))

def sum_of_best(splits, sob, level=0):
    if len(splits) == 1:
        return None
    last_start = 0
    best = 0
    for i, split in enumerate(splits):
        if split.level <= level:
            sub_sob = sum_of_best(splits[last_start:i+1], sob, level+1)
            last_start = i + 1
            out_sob = sob[(split, level)]
            if sub_sob is not None and out_sob is not None and sub_sob < out_sob:
                out_sob = sub_sob
            if out_sob is None:
                return None
            best += out_sob
    return best


RED = '\x1b[31m'
GREEN = '\x1b[32m'
GOLD = '\x1b[33m'
NORMAL = '\x1b[0m'

def pb_stats(sm, split, level):
    if sm.compare_pb is not None:
        pb_time = sm.compare_pb.segment_time(split, level)
        pb_tot = sm.compare_pb[split]
    else:
        pb_time = None
        pb_tot = None
    return pb_time, pb_tot

def render_column(col, width, left=True):
    curlen = len(col[0] % (('',)*(len(col)-1)))
    result = col[0] % col[1:]
    if curlen < width:
        if left:
            result += ' ' * (width - curlen)
        else:
            result = ' ' * (width - curlen) + result
    return result

def render_line(cols, level, widths):
    return '  '*level + ''.join(render_column(col, width - (0 if i == 0 else 0)) for i, (col, width) in enumerate(zip(cols, widths))) + '\n'

def render_current_split(sm, split, level):
    pb_time, _ = pb_stats(sm, split, level)

    cur_time = sm.current_segment_time(level)
    if cur_time is not None:
        cur_time_str = fmt_time(cur_time, ms_decimals=1)
    else:
        cur_time_str = '--'

    if pb_time is None:
        pb_time_str = '--'
        color = NORMAL
    else:
        pb_time_str = fmt_time(pb_time, ms_decimals=1)
        if cur_time is None:
            color = NORMAL
        elif cur_time < pb_time:
            color = GREEN
        else:
            color = RED
    col_0 = (split.level_name(level) + ':',)
    col_1 = ('%s' + cur_time_str + '%s' + '/' + pb_time_str, color, NORMAL)
    col_2 = ('',)
    return col_0, col_1, col_2

def render_upcoming_split(sm, split, level):
    pb_time, pb_tot = pb_stats(sm, split, level)

    if pb_time is None:
        col_1 = '--'
    else:
        col_1 = fmt_time(pb_time, ms_decimals=1)
    if pb_tot is None:
        col_2 = '--'
    else:
        col_2 = fmt_time(pb_tot, ms_decimals=1)
    col_0 = split.level_name(level) + ':'
    return (col_0,), (col_1,), (col_2,)

def render_past_split(sm, split, level):
    pb_time, pb_tot = pb_stats(sm, split, level)

    cur_time = sm.current_times.segment_time(split, level)
    cur_tot = sm.current_times[split]

    best_time = None if sm.compare_best is None else sm.compare_best[(split, level)]

    if cur_time is None:
        seg_time_str = '--'
        seg_color = NORMAL
    elif pb_time is None:
        seg_time_str = fmt_time(cur_time, ms_decimals=0)
        seg_color = NORMAL
    else:
        seg_time_str = fmt_time(cur_time - pb_time, sign=True, ms_decimals=1)
        if cur_time < pb_time:
            seg_color = GREEN
        else:
            seg_color = RED

        if best_time is not None and cur_time < best_time:
            seg_color = GOLD

    if best_time is None:
        seg_best_str = '--'
    elif pb_time is None:
        seg_best_str = fmt_time(best_time, sign=False, ms_decimals=0)
    else:
        seg_best_str = fmt_time(pb_time - best_time, sign=False, ms_decimals=1)


    if cur_tot is None:
        tot_time_str = '--'
        tot_diff_str = '--'
        tot_color = NORMAL
    else:
        tot_time_str = fmt_time(cur_tot, ms_decimals=1)

        if pb_tot is None:
            tot_diff_str = '--'
            tot_color = NORMAL
        else:
            tot_diff_str = fmt_time(cur_tot - pb_tot, sign=True, ms_decimals=1)
            if cur_tot < pb_tot:
                tot_color = GREEN
            else:
                tot_color = RED


    col_0 = (split.level_name(level) + ':',)
    col_1 = ('%s' + seg_time_str + '%s/' + seg_best_str, seg_color, NORMAL)
    col_2 = (tot_time_str + '/%s' + tot_diff_str + '%s', tot_color, NORMAL)
    return col_0, col_1, col_2

def render_split(sm, split, level):
    refsplit = sm.current_split(level)
    if refsplit == split:
        cols = render_current_split(sm, split, level)
    elif split in sm.current_times:
        cols = render_past_split(sm, split, level)
    else:
        cols = render_upcoming_split(sm, split, level)
    return render_line(cols, level, [35, 20, 20])

def format_splits(sm, termsize=True):
    if termsize:
        _, term_rows = os.get_terminal_size()
    else:
        _, term_rows = 100000, 100000

    rows = []
    last_level = 0
    for i, split in enumerate(sm.route.splits):
        if split.level > last_level:
            target_level = last_level
            while target_level < split.level:
                j = i + 1
                while True:
                    if sm.route.splits[j].level == target_level:
                        rows.append((sm.route.splits[j], target_level))
                        break
                    j += 1
                target_level += 1
            rows.append((split, split.level))
        elif split.level < last_level:
            rows.append((split, last_level))
        else:
            rows.append((split, split.level))
        last_level = split.level

    refsplit = sm.current_split(1000)
    current_idx = len(rows) - 1
    for i, (split, _) in enumerate(rows):
        if split is refsplit:
            current_idx = i

    bottom_row = [rows[-1]] if current_idx != len(rows) - 1 else []
    prev_rows = rows[:current_idx]
    later_rows = rows[current_idx+1:-1]

    render_rows = [rows[current_idx]]
    current_render_idx = 0
    if len(render_rows) < term_rows:
        render_rows.extend(bottom_row)
    while len(render_rows) < term_rows and prev_rows:
        render_rows.insert(0, prev_rows.pop(-1))
        current_render_idx += 1
    later_rows_added = 0
    while len(render_rows) < term_rows and later_rows:
        render_rows.insert(current_render_idx + 1 + later_rows_added, later_rows.pop(0))
        later_rows_added += 1
    while len(render_rows) < term_rows:
        render_rows.insert(-1, (None, None))


    data = ''.join(render_split(sm, split, level) if split is not None else '\n' for split, level in render_rows)
    return data.rstrip()

def print_splits(sm, formatter):
    print('\x1b[H\x1b[J' + formatter(sm), end='')  # move to origin; erase screen

def main(route, pb=None, best=None, renderer=None):
    if pb is None and best is None and type(route) is str:
        pb = '.'.join(route.split('.')[:-1]) + '.pb'
        best = '.'.join(route.split('.')[:-1]) + '.best'
    asi = AutoSplitterInfo()
    pb_filename = None
    if renderer is None:
        renderer = functools.partial(print_splits, formatter=format_splits)

    if type(route) is str:
        route = open_pickle_or_yaml(route)
    if type(pb) is str:
        pb_filename = pb
        try:
            pb = open_pickle_or_yaml(pb)
        except FileNotFoundError:
            pb = None
    if type(best) is str:
        best_filename = best
        try:
            best = open_pickle_or_yaml(best)
        except FileNotFoundError:
            best = None

    sm = NotifSplitsManager(asi, route, pb, best)
    listener.start()
    try:
        print('\x1b[?25l')  # hide cursor
        subprocess.check_call('stty -echo', shell=True)
        while True:
            try:
                while action_queue:
                    action = action_queue.pop(0)
                    if action == 'skip':
                        old_piece = sm.current_piece
                        sm.skip()
                        notify('Skipped %s' % old_piece.name, 'Next trigger: %s' % sm.current_piece.name, 3)
                    elif action == 'rewind':
                        old_piece = sm.current_piece
                        sm.rewind()
                        notify('Rewound from %s' % old_piece.name if old_piece is not None else '[done]', 'Next trigger: %s' % sm.current_piece.name, 3)
                    elif action == 'reset':
                        sm.commit()
                        sm.reset()
                        notify('Reset', '', 3)


                sm.update()
                renderer(sm)

                global cancel_show_at
                if cancel_show_at is not None and time.time() >= cancel_show_at:
                    n.close()
                    cancel_show_at = None

                time.sleep(0.010)
            except KeyboardInterrupt:
                sm.commit()
                break
    finally:
        subprocess.check_call('stty echo', shell=True)
        print('\x1b[34h\x1b[?25h')  # restore cursor
        if pb_filename is not None and len(sm.compare_pb) == len(sm.route.splits):
            print('saving', pb_filename)
            show_splits(sm.route, sm.compare_pb)
            save_yaml(pb_filename, sm.compare_pb)
        if best_filename is not None:
            print('saving', best_filename)
            sob = sum_of_best(sm.route.splits, sm.compare_best)
            if sob is not None:
                print('sum of best:', fmt_time(sob))
            save_yaml(best_filename, sm.compare_best)

# finished:
# Segment name:  1.23/+1.23  1:32.45/+1.23
# that's cur seg time and cur/pb time diff and cur cum time

# in progress:
# Segment name:   1.23/1.23
# that's cur time and pb time

# upcoming:
# Segment name:   1.23  1:23.45
# that's pb time and pb cum time

if __name__ == '__main__':
    import sys
    if sys.argv == 1:
        main('anypercent.route')
    else:
        main(sys.argv[1])
