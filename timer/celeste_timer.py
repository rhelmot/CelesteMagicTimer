#!/usr/bin/env python3

import os
import struct
import threading
import time
import collections
import random
import json

# 00 string Level;
# 08 int Chapter;
# 0c int Mode;
# 10 bool TimerActive;
# 11 bool ChapterStarted;
# 12 bool ChapterComplete;
# 18 long ChapterTime;
# 20 int ChapterStrawberries;
# 24 bool ChapterCassette;
# 25 bool ChapterHeart;
# 28 long FileTime;
# 30 int FileStrawberries;
# 34 int FileCassettes;
# 38 int FileHearts;
# 40 int CurrentChapterCheckpoints;

asi_path = os.environ.get('ASI_PATH', '/dev/shm/autosplitterinfo')

def split_time(filetime):
    neg = filetime < 0
    if neg:
        filetime = -filetime
    ms = filetime % 1000
    se = filetime // 1000 % 60
    mi = filetime // 1000 // 60 % 60
    hr = filetime // 1000 // 60 // 60
    return (neg, hr, mi, se, ms)

def fmt_time(tup, ms_decimals=3, full_width=False, sign=False):
    if type(tup) is int:
        tup = split_time(tup)

    neg, hr, mi, se, ms = tup
    if ms_decimals > 0:
        if ms_decimals == 1:
            ms //= 100
        elif ms_decimals == 2:
            ms //= 10
        ms_str = ('.%%0%dd' % ms_decimals) % ms
    else:
        ms_str = ''

    if hr or mi or full_width:
        se_str = '%02d' % se
    else:
        se_str = '%d' % se

    if hr or full_width:
        mi_str = '%02d:' % mi
    else:
        if mi:
            mi_str = '%d:' % mi
        else:
            mi_str = ''

    if hr or full_width:
        hr_str = '%d:' % hr
    else:
        hr_str = ''

    if sign or neg:
        sign_str = '-' if neg else '+'
    else:
        sign_str = ''

    return sign_str + hr_str + mi_str + se_str + ms_str


class AutoSplitterInfo:
    def __init__(self, filename=asi_path):
        self.all_attrs = ('chapter', 'mode', 'timer_active', 'chapter_started', 'chapter_complete', 'chapter_time', 'chapter_strawberries', 'chapter_cassette', 'chapter_heart', 'file_time', 'file_strawberries', 'file_cassettes', 'file_hearts', 'chapter_checkpoints', 'in_cutscene', 'death_count', "level_name")
        self.chapter = 0
        self.mode = 0
        self.timer_active = False
        self.in_cutscene = False
        self.death_count = 0
        self.level_name = ""

        self.chapter_started = False
        self.chapter_complete = False
        self.chapter_time = 0
        self.chapter_strawberries = 0
        self.chapter_cassette = False
        self.chapter_heart = False
        self.chapter_checkpoints = 0

        self.file_time = 0
        self.file_strawberries = 0
        self.file_cassettes = 0
        self.file_hearts = 0

        if not os.path.exists(filename):
            print('waiting for', filename, '...')
            while not os.path.exists(filename):
                time.sleep(1)

        self.fp = open(filename, 'rb')
        self.live = True

        self.thread = threading.Thread(target=self.update_loop)
        self.thread.daemon = True
        self.thread.start()

    @property
    def chapter_name(self):
        if self.chapter == 0:
            return 'Prologue'
        if self.chapter == 8:
            return 'Epilogue'
        if self.chapter == 10:
            return '9'
        if self.mode == 0:
            side = 'a'
        elif self.mode == 1:
            side = 'b'
        else:
            side = 'c'
        return '%d%s' % (self.chapter, side)

    def __getitem__(self, k):
        try:
            return getattr(self, k)
        except AttributeError as e:
            raise KeyError(k) from e

    @property
    def dict(self):
        return {x: getattr(self, x) for x in self.all_attrs}

    def update_loop(self):
        fmtstring = struct.Struct('Qii???QI??QIIIxxxxI?i100s')
        while self.live:
            last_tick = time.time()
            self.fp.seek(0)
            dat = self.fp.raw.read(fmtstring.size)
            _, self.chapter, self.mode, self.timer_active, \
                self.chapter_started, self.chapter_complete, \
                chapter_time, self.chapter_strawberries, \
                self.chapter_cassette, self.chapter_heart, file_time, \
                self.file_strawberries, self.file_cassettes, self.file_hearts, \
                self.chapter_checkpoints, self.in_cutscene, self.death_count, level_name \
                = fmtstring.unpack(dat)

            self.chapter_time = chapter_time // 10000
            self.file_time = file_time // 10000
            self.level_name = level_name.split(b'\0')[0].decode()

            timeout = last_tick + 0.001 - time.time()
            if timeout > 0:
                time.sleep(timeout)

class Trigger:
    def __init__(self, name, end_trigger):
        self.name = name
        self.end_trigger = end_trigger

    def check_trigger(self, asi): # pylint: disable=unused-argument
        return eval(self.end_trigger) # pylint: disable=eval-used

    def __repr__(self):
        return '<Trigger %s>' % self.name

class Split:
    def __init__(self, names, level=0):
        if type(names) == str:
            names = [names]
        if len(names) == 0:
            raise ValueError("Need at least one name")
        self.names = names
        self.level = level
        self.identity = random.randrange(2**64)

    def level_name(self, level):
        if level < self.level:
            raise ValueError("Why are you trying to render %s at level %d?" % (self, level))
        try:
            return self.names[level - self.level]
        except IndexError:
            return self.names[-1]

    def __eq__(self, other):
        return hasattr(other, 'identity') and self.identity == other.identity

    def __hash__(self):
        return hash(self.identity)

    def __repr__(self):
        return '<Split %s>' % self.names[0]

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        # migration
        if 'name' in state:
            state['names'] = [state.pop('name')]
        self.__dict__.update(state)

class StartTimer:
    def __repr__(self):
        return '<StartTimer>'

notpassed = object()
class SplitsRecord(collections.OrderedDict):
    def segment_time(self, split, level=0, fallback=notpassed):
        found_prev = None
        for cur in self:
            if cur == split:
                break
            if cur.level <= level:
                found_prev = cur
        else:
            if fallback is not notpassed:
                return fallback
            raise KeyError(split)

        if found_prev is None:
            return self[split]
        elif self[split] is None or self[found_prev] is None:
            return None
        else:
            return self[split] - self[found_prev]

class Route(collections.UserList):
    def __init__(self, name, time_field, pieces, level_names, reset_trigger):
        if type(pieces[-1]) is not Split or pieces[-1].level != 0:
            raise TypeError("Last piece of route must be top-level Split")
        super().__init__(pieces)
        self.name = name
        self.time_field = time_field
        self.levels = max(piece.level for piece in pieces if type(piece) is Split) + 1
        self.splits = [x for x in self if type(x) is Split]
        self.level_names = level_names
        self.reset_trigger = reset_trigger

    def __getstate__(self):
        return (list(self), self.name, self.time_field, self.level_names, self.reset_trigger)

    def __setstate__(self, state):
        if type(state) is dict:
            self.__dict__.update(state)
        elif len(state) == 3:
            self.__init__(state[1], state[2], state[0], ['Segment', 'Subsegment'], None)
        else:
            self.__init__(state[1], state[2], state[0], state[3], state[4])

    def split_idx(self, i, level=0):
        while type(self[i]) is not Split or self[i].level > level:
            i += 1
            if i >= len(self):
                return None
        return self.splits.index(self[i])

    @property
    def all_subsegments(self):
        prev = None
        for split in self.splits:
            if prev is not None:
                for level in range(prev.level, split.level, -1):
                    yield (split, level)

            yield (split, split.level)
            prev = split

class JsonRoute(Route):
    def __init__(self, path_to_route):
        with open(path_to_route) as f:
            decoded_json = json.load(f)
        name = decoded_json["name"]
        time_field = decoded_json["time_field"]
        reset_trigger = decoded_json["reset_trigger"]
        level_names = decoded_json["level_names"]
        pieces = parsejsonroute(decoded_json["pieces"])
        super().__init__(name, time_field, pieces, level_names, reset_trigger)

def parsejsonroute(route_json, pieces=[], level=0):
    if len(route_json) == 0:
        return None
    last_split_name = None
    if route_json[-1]["type"] == "split":
        last_split_name = route_json[-1]["name"]
    for count, j_piece in enumerate(route_json):
        if j_piece["type"] == "split":
            pieces_last_split_name = parsejsonroute(j_piece["pieces"], pieces, level+1)
            # don't add a split entry for the last split of a higher level split
            if count == len(route_json) - 1 and level != 0:
                break
            split_names = [j_piece["name"]]
            if pieces_last_split_name:
                split_names.append(pieces_last_split_name)
            split = Split(split_names, level)
            pieces.append(split)
        if j_piece["type"] == "trigger":
            pieces.append(Trigger("whatever", j_piece["trigger"]))
    if level == 0:
        return pieces
    return last_split_name


class SplitsManager:
    def __init__(self, asi, route, compare_pb=None, compare_best=None):
        self.asi = asi
        self.route = route
        self.compare_pb = compare_pb if compare_pb is not None else SplitsRecord()
        self.compare_best = compare_best if compare_best is not None else {}
        self.current_times = SplitsRecord()
        self.current_piece_idx = 0
        self.start_time = 0
        self.started = False

        # migration
        parents = {}
        for split in self.route.splits:
            parents[split.level] = split

            if split not in self.compare_pb:
                self.compare_pb[split] = None
            else:
                self.compare_pb.move_to_end(split)

            for level in range(split.level, self.route.levels):
                key = (split, level)
                if key not in self.compare_best:
                    self.compare_best[key] = None

    @property
    def done(self):
        return self.current_piece_idx >= len(self.route)

    @property
    def current_piece(self):
        if self.done:
            return None
        return self.route[self.current_piece_idx]

    def _current_split_idx(self, level=0):
        idx = self.route.split_idx(self.current_piece_idx, level)
        if idx is None:
            return None
        while self.route.splits[idx].level > level:
            idx += 1
        return idx

    def _forward_split(self, idx, level=0):
        idx += 1
        if idx >= len(self.route.splits):
            return None
        while self.route.splits[idx].level > level:
            idx += 1
            if idx >= len(self.route.splits):
                return None
        return idx

    def _backwards_split(self, idx, level=0):
        idx -= 1
        if idx < 0:
            return None
        while self.route.splits[idx].level > level:
            idx -= 1
            if idx < 0:
                return None
        return idx

    def current_split(self, level=0):
        if self.done:
            return None
        idx = self._current_split_idx(level)
        return self.route.splits[idx]

    def previous_split(self, level=0):
        idx = self._current_split_idx(level)
        idx = self._backwards_split(idx, level)
        if idx is None:
            return None
        return self.route.splits[idx]

    def is_segment_done(self, split):
        return self.current_piece_idx > self.route.index(split)

    @property
    def current_time(self):
        return self.asi[self.route.time_field] - self.start_time

    def current_segment_time(self, level=0):
        if self.done:
            return None
        prev_split = self.previous_split(level)
        if prev_split is None:
            return self.current_time
        split_start = self.current_times[prev_split]
        if split_start is None:
            return None
        return self.current_time - split_start

    def best_possible_time(self):
        return None

    def split(self, split):
        self.current_times[split] = self.current_time

    def commit(self):
        if self.route.splits[-1] in self.current_times:
            cur_time = self.current_times[self.route.splits[-1]]
            pb_time = self.compare_pb[self.route.splits[-1]]
            if pb_time is None or cur_time < pb_time:
                self.compare_pb = self.current_times

        # TODO: do we care about not mutating this reference?
        self.compare_best = dict(self.compare_best)
        for key in self.route.all_subsegments:
            split, level = key
            seg = self.current_times.segment_time(split, level, None)
            best = self.compare_best[key]
            if seg is not None and (best is None or seg < best):
                self.compare_best[key] = seg

    def reset(self):
        self.current_piece_idx = 0
        self.current_times = SplitsRecord()
        self.started = False
        self.start_time = 0

    def skip(self, n=1):
        while not self.done:
            if type(self.current_piece) is Split:
                self.current_times[self.current_piece] = None
                self.current_piece_idx += 1
            elif type(self.current_piece) is StartTimer:
                self.start_time = self.asi[self.route.time_field]
                self.current_piece_idx += 1
            else:
                if n:
                    self.started = True
                    self.current_piece_idx += 1
                    n -= 1
                else:
                    break

    def rewind(self, n=1):
        while self.current_piece_idx:
            if type(self.current_piece) is Split:
                del self.current_times[self.current_piece]
                self.current_piece_idx -= 1
            elif type(self.current_piece) is StartTimer:
                self.current_piece_idx -= 1
                self.started = False
            else:
                if n:
                    self.current_piece_idx -= 1
                    n -= 1
                else:
                    if self.current_piece.check_trigger(self.asi):
                        self.current_piece_idx -= 1
                    else:
                        break


    def update(self):
        if type(self.route.reset_trigger) is Trigger and self.route.reset_trigger.check_trigger(self.asi):
            self.commit()
            self.reset()

        if self.done:
            return

        while not self.done:
            if type(self.current_piece) is Split:
                self.split(self.current_piece)
                self.current_piece_idx += 1
            elif type(self.current_piece) is StartTimer:
                self.start_time = self.asi[self.route.time_field]
                self.current_piece_idx += 1
            else:
                if self.current_piece.check_trigger(self.asi):
                    self.started = True
                    self.current_piece_idx += 1
                else:
                    break

def parse_mapname(line):
    if line.lower() == 'farewell':
        return 10, 0
    if line.lower() == 'prologue':
        return 0, 0

    if line.isdigit():
        side = 'a'
    else:
        line, side = line[:-1], line[-1]
        side = side.lower()
    assert side in ('a', 'b', 'c')
    mode = ord(side) - ord('a')
    chapter = int(line)
    if chapter >= 8:
        chapter += 1
    return chapter, mode

def _main():
    asi = AutoSplitterInfo()
    max_width = max(len(attr) for attr in asi.all_attrs)
    while True:
        data = '\x1b\x5b\x48\x1b\x5b\x4a'
        time.sleep(0.01)
        for attr in asi.all_attrs:
            val = asi.dict[attr]
            if attr.endswith('_time'):
                val = fmt_time(val)
            data += attr.ljust(max_width) + ': ' + str(val) + '\n'
        print(data)

if __name__ == '__main__':
    _main()
