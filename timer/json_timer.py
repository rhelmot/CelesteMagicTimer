#!/usr/bin/env python3

import argparse
import csv
import enum
import json
import mmap
import os
import struct
import threading
import time

# The autosplitter is responsible for reading and parsing a piece of
#   shared memory from the tracer (see `celeste_tracer.c`). It forks
#   a thread responsible for scanning this memory on a timer and updates
#   a dict at `self`. RouteWatcher checks these values to see if
#   conditions specified in route triggers are met.
class AutoSplitter(dict):
    # these keys (and the associated Struct) correspond exactly to the binary
    # format exported by the tracer; order is significant!
    _keys = (
        '__level', 'chapter', 'mode', 'timer_active', 'chapter_started',
        'chapter_complete', '_chapter_time', 'chapter_strawberries',
        'chapter_cassette', 'chapter_heart', '_file_time',
        'file_strawberries','file_cassettes', 'file_hearts',
        'chapter_checkpoints', 'in_cutscene', 'death_count', '_level_name'
    )
    __asikeyfmt = struct.Struct('8sii???QI??QIIIxxxxI?i100s')

    # These are the autosplitter values as accessed externally to this class.
    # Some internal keys (__key) aren't intended for public use; keys prefixed
    # with _ are available without the prefix in a modified (more useful) form
    _extras = ("menu",)
    public_keys = tuple(k.lstrip('_') for k in _keys + _extras if k[:2] != '__')

    def __init__(self, filepath, tickrate=0.001):
        # using mmap should be faster as it avoids overhead from calling read
        self.__fp = open(filepath, 'rb')
        self.__shmem = mmap.mmap(self.__fp.fileno(),
                                 self.__asikeyfmt.size,
                                 access=mmap.ACCESS_READ)

        self.__tickrate = tickrate
        self.__thread = threading.Thread(target=self._update_loop)
        self.__thread.daemon = True
        self.__thread.start()

    @property
    def chapter_time(self):
        return self.get('_chapter_time', 0) // 10000

    @property
    def file_time(self):
        return self.get('_file_time', 0) // 10000

    @property
    def level_name(self):
        return self['_level_name'].partition(b'\0')[0].decode()

    # additional convenience property detects chapter selection screen
    @property
    def menu(self):
        return self['chapter'] == -1

    # overrides dict method to allow access to `chapter_time` and friends
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            return super().__getattribute__(key)

    def __del__(self):
        self.__shmem.close()
        self.__fp.close()

    def _update_loop(self):
        while True:
            last_tick = time.time()
            for key, val in zip(self._keys, self.__asikeyfmt.unpack(self.__shmem)):
                self[key] = val

            timeout = last_tick + self.__tickrate - time.time()
            if timeout > 0:
                time.sleep(timeout)


# An Event is a Split or Trigger in a linear playthrough of a route.
class Event():
    # flags indicating the type of event
    START_SPLIT = enum.auto()
    END_SPLIT = enum.auto()
    TRIGGER = enum.auto()
    def __init__(self, ev_type, name=""):
        self.name = name
        self.action = ev_type

    def __repr__(self):
        return self.name

# classes for unified handling of events
class Trigger(Event):
    def __init__(self, t_dict, name):
        self.requirements = t_dict
        super().__init__(Event.TRIGGER, name)

class StartSplit(Event):
    def __init__(self, split):
        self.split = split
        super().__init__(Event.START_SPLIT, split.path_to_piece)

class EndSplit(Event):
    def __init__(self, split):
        self.split = split
        super().__init__(Event.END_SPLIT, split.path_to_piece)

# The Split class uniquely refers to a split as defined in a Route file
# and should be passed wherever needed.
class Split():
    def __init__(self, path_to_piece, name, level=0):
        self.name = name

        # path_to_piece is implementation-defined by the Route format
        # it stores a string representing the path through the route tree
        # to a particular split, e.g. `City->Crossing`
        #
        # It is likely but not guaranteed to be unique. It is only used to
        # provide a visual identifier to the user, e.g. in PB files.
        self.path_to_piece = path_to_piece

        # The highest level splits contain all the other splits, so their
        # sum is equal to the time for the whole route. This value can also
        # be used by splits printer to indent subsplits.
        self.level = level

        # These attributes are updated to provide a timer
        self.start_time = None
        self.elapsed_time = None

        # Indicate whether a split is marked as complete or not
        self.active = False

# implements a JSON based route format
# see `anypercent.json` for example syntax
class JsonRoute():
    def __init__(self, filepath, allow_eval):
        self.allow_eval = allow_eval
        with open(filepath) as f:
            data = json.load(f)
            self.name = data['name'] # name for the route that should print in header
            self.time_field = data['time_field'] # route timed with chapter / file time
            if not self.time_field in ('chapter_time', 'file_time'):
                raise ValueError('JSON time field must be "chapter_time" or "file_time"')
            self.reset_trigger = data.get('reset_trigger') # optional
            self.route = data['splits']
            # contains a list of splits in printing order
            self.splits = []
            # contains splits + triggers in run order
            self.events = []
            # the parser creates splits + events from the route JSON
            self.__parse_json_route(self.route)

    # A recursive route parser for the non-metadata portion of the
    #   JSON route format. Returns only error values, `route` and `splits`
    #   are modified in place. Splits are in natural / printing order.
    # The `event` list contains all the events in the order they should
    #   happen in the run. This is used by the watcher to run through linearly.
    #   There is an event for both the start and end of a split.
    def __parse_json_route(self, route, split_path='', level=0):
        for piece in route:
            # The route format cannot have splits with sibling triggers.
            if 'splits' in piece and 'triggers' in piece:
                raise AssertionError(''
                    'Splits in your route file should never have triggers as siblings.\n'
                    'If they do, you can have "missing" time between events.\n'
                    'If you are sure you know what you\'re doing, you can remove this check.'
                )

            # used to make things easy for users only
            # e.g. we print it in PB file for easy editing
            path_to_piece = split_path + piece['name']

            split = Split(
                path_to_piece = path_to_piece,
                name = piece['name'],
                level = level
            )

            self.splits.append(split)
            split_event = StartSplit(split)
            self.events.append(split_event)

            # the recursive step
            if 'splits' in piece:
                self.__parse_json_route(
                    route = piece['splits'],
                    split_path = path_to_piece + '->',
                    level = level + 1
                )

            if 'triggers' in piece:
                triggers = piece['triggers']
                for i, trigger in enumerate(triggers):
                    t_name = f"{split_path}trigger{i+1}"
                    if 'eval' in trigger and not self.allow_eval:
                        raise ValueError('Route file used eval, not allowed.')
                    # sanity checking
                    for key in trigger:
                        if not key in AutoSplitter.public_keys and not key == 'eval':
                            raise ValueError(f'Invalid trigger "{key}" in {t_name}')
                    trigger_event = Trigger(trigger, name=t_name)
                    self.events.append(trigger_event)

            # finally, end the split we started above
            split_event_end = EndSplit(split)
            self.events.append(split_event_end)

# The core livesplit class: walks a route tree waiting for triggers to fire
# updating splits as it goes, calling out to a print function every `timeout`
#
# Implementation note: because we scan only every 0.01s (by default), it's
# very important that splits never have triggers as siblings in the JSON. They
# can take enough time that we miss the starting frame of the split. Without
# sibling triggers, splits will start automatically when the previous split
# ends (or when the file is created), so we never miss it. The file timer
# freezes when the chapter ends, so we *never* miss the ending frame anyway.
# Presumably it doesn't matter if we miss a checkpoint split by a frame.
class RouteWatcher():
    def __init__(self, route, asi, printer, timeout=0.01):
        self.route = route
        self.asi = asi
        self.callback = printer.print
        self.timeout = timeout
        self.needsreset = False
        self.started = False

    # a function that sleeps, calls print, and then checks whether a
    # route reset condition is fulfilled. Reset may not contain eval.
    def __wait(self):
        time.sleep(self.timeout)
        self.callback(self)
        # Should this only run every 0.1 or something?
        if self.started and self.route.reset_trigger:
            for key, val in self.route.reset_trigger.items():
                if not self.asi[key] == val:
                    return
            self.needsreset = True

    # A simple utility function to wait for a trigger to fire
    # FIXME: add some checks for handling keyboard input
    def triggerwait(self, trigger):
        asi = self.asi # do not delete: can be referenced by `eval`
        complete = False
        while not complete:
            complete = True
            for key, val in trigger.items():
                if key == 'type':
                    continue
                elif key == 'eval':
                    if not eval(val):
                        complete = False
                        break
                else:
                    if asi[key] != val:
                        complete = False
                        break
            if not complete:
                self.__wait()
                if self.needsreset:
                    return

    def reset(self):
        self.started = False
        self.needsreset = False
        for split in self.route.splits:
            split.elapsed_time = None
            split.start_time = None
            split.active = False

    @property
    def time(self):
        if self.route.time_field == 'chapter_time':
            return self.asi['chapter_time']
        return self.asi['file_time']

    # Watch the list of events, pausing at triggers until the condition is met
    # Calls the print callback every `timeout` seconds
    # returns True if event list is completed, false if returning for other reason
    def watch(self):
        # normally we indicate that we have started (making reset available) only after
        # seeing the first trigger, but if the timer is started too late, we might miss
        # the trigger and be left hanging indefinitely
        if self.time != 0:
            self.started = True
        try:
            for event in self.route.events:
                if event.action == Event.START_SPLIT:
                    event.split.active = True
                    event.split.start_time = self.time
                elif event.action == Event.END_SPLIT:
                    time_elapsed = self.time - event.split.start_time
                    event.split.elapsed_time = time_elapsed
                    event.split.active = False
                elif event.action == Event.TRIGGER:
                    self.triggerwait(event.requirements)
                    self.started = True
                    if self.needsreset:
                        return False
                self.callback(self)
        except KeyboardInterrupt:
            return False

        return True

# A wrapper around a simple CSV format to handle PB information
#
# format of the CSV file is as follows:
# [path_to_piece, split_pb_time, pb_time, split_average, split_count]
#
# `split_pb_time` is the best time for that split, `pb_time` means
# the split achieved with the PB for the overall route
class PersonalBest():
    def __init__(self, filepath, route):
        self.filepath = filepath
        # route is required because splits file doesn't contain enough
        # information to reconstruct the route
        self.route = route
        self.splits = []
        try:
            with open(self.filepath, newline='') as f:
                reader = csv.reader(f)
                for line in reader:
                    self.splits.append([
                            line[0],        # path_to_piece
                            float(line[1]), # split_pb_time
                            float(line[2]), # pb_split_time
                            float(line[3]), # split_average_time
                            int(line[4])    # split_count
                    ])
        except FileNotFoundError:
            pass
        self.generate_cached_values()

    # cache various splits for easy access from printers and so on
    def generate_cached_values(self):
        self.split_pbs = [x[1] for x in self.splits]
        self.pb_splits = [x[2] for x in self.splits]
        self.average_splits = [x[3] for x in self.splits]

        # these will be zero if the PB file doesn't exist yet
        # important to check truthiness when using
        # important: only include top level splits in sum
        self.pb = 0
        self.sum_split_pbs = 0
        self.sum_average_splits = 0
        for i in range(len(self.splits)):
            if self.route.splits[i].level == 0:
                self.pb += self.pb_splits[i]
                self.sum_split_pbs += self.split_pbs[i]
                self.sum_average_splits += self.average_splits[i]

    # rewrites the PB file with the latest data after a run
    def update(self, new_splits):
        # if the PB file is empty, we make a new one
        if self.pb == 0:
            self.make_new_pb_file(new_splits)
            return

        # otherwise compare with existing PB times
        total_time = None
        # only have total time if the route was actually completed
        if not None in [sp.elapsed_time for sp in new_splits]:
            total_time = sum([sp.elapsed_time for sp in new_splits if sp.level == 0])
        for i, newsplit in enumerate(new_splits):
            # update split PB if improved
            if newsplit.elapsed_time and newsplit.elapsed_time < self.splits[i][1]:
                self.splits[i][1] = newsplit.elapsed_time
            # update PB splits if overall PB
            if total_time and total_time < self.pb:
                self.splits[i][2] = newsplit.elapsed_time
            # update average splits
            if newsplit.elapsed_time:
                self.splits[i][3] = ((self.splits[i][3] * self.splits[i][4] + newsplit.elapsed_time) /
                                    (self.splits[i][4] + 1))
                # update count (used to calculate averages)
                self.splits[i][4] += 1

        # write to file
        with open(self.filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            for row in self.splits:
                writer.writerow(row)

        # update cached values
        self.generate_cached_values()

    # make a new PB file from scratch
    # times for each split are the same since we only have one run
    def make_new_pb_file(self, new_splits):
        # don't save initial splits if route hasn't been completed
        if None in [sp.elapsed_time for sp in new_splits]:
            return
        with open(self.filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            for split in new_splits:
                writer.writerow([
                        split.path_to_piece,
                        split.elapsed_time,
                        split.elapsed_time,
                        split.elapsed_time,
                        1
                ])

# for debugging, an easy way to print nothing
class DummyPrinter():
    def print(self, arg):
        return

# The default implementation of a splits printer; allows comparing with a PB
#   file, see `PersonalBest` for implementation.
# Different implementations of this class are possible, e.g. some kind of GUI
# Note that instances of this class are route specific because they require a
# PB instance, which wraps a route specific PB file.
class SplitsPrinter():
    def __init__(self, pb, compare_pb, compare_splits, compare_average):
        self.pb = pb
        self.route = pb.route
        self.compare_pb = compare_pb
        self.compare_splits = compare_splits
        self.compare_average = compare_average

        # this value is prepended to each additional indendation level
        self.padding = '  '

        # calculate the largest space that can be occupied by name + padding
        max_padding = len(self.padding) * max([sp.level for sp in pb.route.splits])
        self.max_name_len = max([len(sp.name) for sp in pb.route.splits])
        self.max_name_len = max(self.max_name_len, len(pb.route.name))
        self.max_name_len += max_padding

        # generate header
        self.header_text = 'Split'.ljust(self.max_name_len)
        self.header_text +=     '        Time'
        if self.compare_pb:
            self.header_text += '          PB'
        if self.compare_splits:
            self.header_text += '      Splits'
        if self.compare_average:
            self.header_text += '     Average'

        # handle case where pb file is empty
        if self.pb.pb == 0:
            self.compare_pb = False
            self.compare_splits = False
            self.compare_average = False

    def get_hms_from_msecs(self, msecs):
        secs = msecs / 1000
        mins = int(secs) // 60
        secs %= 60
        hrs = mins // 60
        mins %= 60
        if hrs > 0:
            return f'{hrs}:{mins:02}:{secs:06.3f}'
        if mins > 0:
            return f'{mins}:{secs:06.3f}'
        return f'{secs:.3f}'

    # routewatcher is implementation defined by RouteWatcher. See that class
    # for properties available to the printer; it is guaranteed to provide
    # the properties `route` (the Route object for that watcher) and `time`
    # (the current ASI time - either chapter or file - used by the route).
    def print(self, routewatcher):
        # this magical string resets the terminal
        print('\x1b\x5b\x48\x1b\x5b\x4a', end='')

        # print header (pre-generated)
        print(self.header_text)
        print('-' * len(self.header_text))

        for i, split in enumerate(routewatcher.route.splits):
            split_padding = self.padding * split.level
            # either the split is currently active, finished, or never active
            fmt_time = ''
            if split.active:
                fmt_time = self.get_hms_from_msecs(routewatcher.time - split.start_time)
            elif split.elapsed_time:
                fmt_time = self.get_hms_from_msecs(split.elapsed_time)
            line = f'{(split_padding + split.name).ljust(self.max_name_len)} {fmt_time.rjust(11)}'
            if self.compare_pb:
                fmt_time = self.get_hms_from_msecs(self.pb.pb_splits[i])
                line += f' {fmt_time.rjust(11)}'
            if self.compare_splits:
                fmt_time = self.get_hms_from_msecs(self.pb.split_pbs[i])
                line += f' {fmt_time.rjust(11)}'
            if self.compare_average:
                fmt_time = self.get_hms_from_msecs(self.pb.average_splits[i])
                line += f' {fmt_time.rjust(11)}'
            print(line)

        # footer containing the time for the whole file
        fmt_time = self.get_hms_from_msecs(routewatcher.time)
        line = f'{self.route.name.ljust(self.max_name_len)} {fmt_time.rjust(11)}'
        if self.compare_pb:
            fmt_time = self.get_hms_from_msecs(self.pb.pb)
            line += f' {fmt_time.rjust(11)}'
        if self.compare_splits:
            fmt_time = self.get_hms_from_msecs(self.pb.sum_split_pbs)
            line += f' {fmt_time.rjust(11)}'
        if self.compare_average:
            fmt_time = self.get_hms_from_msecs(self.pb.sum_average_splits)
            line += f' {fmt_time.rjust(11)}'
        print('-' * len(self.header_text))
        print(line)


def main():
    parser = argparse.ArgumentParser(description='A simple Celeste timer with a JSON route format.')
    parser.add_argument('--asi', default='/dev/shm/autosplitterinfo',
                        help='path to the auto splitter file created by the tracer')
    parser.add_argument('--pb-file', help='path to a custom PB file for the route', default=None)
    parser.add_argument('--pb', help='compare against your PB', action='store_true', default=False)
    parser.add_argument('--splits', help='compare against your best splits', action='store_true', default=False)
    parser.add_argument('--average', help='compare against your average time', action='store_true', default=False)
    parser.add_argument('--allow-eval', help='allow the route.json file to use eval (warning: insecure and potentially slow)', action='store_true', default=False)
    parser.add_argument('route', help='path to your route.json file')
    args = parser.parse_args()

    # default pb file is just the route path (with .json extension removed) + .pb
    if not args.pb_file:
        if args.route[-5:] == '.json':
            args.pb_file = args.route[:-5] + '.pb'
        else:
            args.pb_file = args.route + '.pb'

    route = JsonRoute(args.route, args.allow_eval)
    pb = PersonalBest(args.pb_file, route)
    printer = SplitsPrinter(pb, args.pb, args.splits, args.average)
    #printer = DummyPrinter()

    # wait until the tracer is started if necessary
    if not os.path.exists(args.asi):
        print('waiting for', args.asi, '...')
        while not os.path.exists(args.asi):
            time.sleep(1)

    asi = AutoSplitter(args.asi)
    watcher = RouteWatcher(route, asi, printer)

    # loop forever; maybe consider putting this behind an option
    while True:
        result = watcher.watch()
        # wait for reset trigger before restarting
        try:
            watcher.triggerwait({'eval': 'False'})
        except KeyboardInterrupt:
            pb.update(route.splits)
            break
        pb.update(route.splits)
        watcher.reset()

if __name__ == '__main__':
    main()
