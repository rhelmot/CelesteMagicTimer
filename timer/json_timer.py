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
#   class attributes. RouteWatcher checks these attributes to see if
#   conditions specified in route triggers are met.
class AutoSplitter:
    __fmtstring = struct.Struct('8sii???QI??QIIIxxxxI?i100s')
    def __init__(self, filepath, tickrate=0.001):
        self._all_attrs = ('__level', 'chapter', 'mode', 'timer_active',
                'chapter_started', 'chapter_complete', 'chapter_time',
                'chapter_strawberries', 'chapter_cassette', 'chapter_heart',
                'file_time', 'file_strawberries', 'file_cassettes',
                'file_hearts', 'chapter_checkpoints', 'in_cutscene',
                'death_count', 'level_name')

        self.__fp = open(filepath, 'rb')
        self.__shmem = mmap.mmap(self.__fp.fileno(),
                                 self.__fmtstring.size,
                                 access=mmap.ACCESS_READ)
        self.__tickrate = tickrate

        self.__thread = threading.Thread(target=self.update_loop)
        self.__thread.daemon = True
        self.__thread.start()

    def __del__(self):
        self.__shmem.close()
        self.__fp.close()

    @property
    def state(self):
        return dict(zip(self._all_attrs, [getattr(self, attr) for attr in self._all_attrs]))

    def update_loop(self):
        while True:
            last_tick = time.time()
            for attr, val in zip(self._all_attrs, self.__fmtstring.unpack(self.__shmem)):
                setattr(self, attr, val)

            self.chapter_time //= 10000
            self.file_time //= 10000
            self.level_name = self.level_name.split(b'\0')[0].decode()

            timeout = last_tick + self.__tickrate - time.time()
            if timeout > 0:
                time.sleep(timeout)

class RouteEvent(enum.Enum):
    START_SPLIT = enum.auto()
    END_SPLIT = enum.auto()
    TRIGGER = enum.auto()

# implements a JSON based route format
# see `anypercent.json` for example syntax
class JsonRoute():
    def __init__(self, filepath):
        with open(filepath) as f:
            data = json.load(f)
            self.name = data["name"] # name for the route that should print in header
            self.time_field = data["time_field"] # route timed with chapter / file time
            self.reset_trigger = data.get("reset_trigger") # optional
            self.route = data["pieces"]
            # contains a list of splits in printing order
            # [path_to_piece, level, split_name, elapsed_time=None]
            self.splits = []
            # contains splits + triggers in run order
            self.events = []
            # the parser creates splits + events from the route JSON
            self.__parse_json_route(self.route, self.splits, self.events)

    # A recursive route parser for the non-metadata portion of the
    #   JSON route format. Returns only error values, `route` and `splits`
    #   are modified in place. Splits are in natural / printing order.
    # The `event` list contains all the events in the order they should
    #   happen in the run. This is used by the watcher to run through linearly.
    #   There is an event for both the start and end of a split.
    def __parse_json_route(self, route, splits, events, split_path="", split_counter=0, level=0):
        for piece in route:
            if piece["type"] == "split":
                # used to make things easy for users only
                # e.g. we print it in PB file for easy editing
                split_name = piece["name"]
                path_to_piece = split_path + split_name

                # the 4th element is reserved for the elapsed time
                splits.append([path_to_piece, level, split_name, None])

                # when we encounter a split for the first time, we start
                # a timer for the split, so add a start_split event
                piece["split"] = split_counter
                events.append((RouteEvent.START_SPLIT, split_counter))

                # we need to keep track of the counter because the same split
                # will need to be ended after we finish recursion
                split_at_current_depth = split_counter
                split_counter += 1

                # the recursive step
                if "pieces" in piece:
                    split_counter = self.__parse_json_route(piece["pieces"], splits, events,
                            path_to_piece + "->", split_counter, level+1)

                # finally, end the split we started above
                events.append((RouteEvent.END_SPLIT, split_at_current_depth))

            elif piece["type"] == "trigger":
                events.append((RouteEvent.TRIGGER, piece["trigger"]))

        # the return value is needed when recursing because integers don't impl copy
        if level != 0:
            return split_counter
        return None

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
# FIXME: Consider enforcing this in the JSON parser.
class RouteWatcher():
    def __init__(self, route, asi, printer, timeout=0.01):
        self.route = route
        self.asi = asi
        self.callback = printer.print
        self.timeout = timeout
        # every split that is currently being timed
        # FIXME: this is small, but maybe still faster to use a set()?
        self.activesplits = []
        # contains the asi start time for every started split
        self.splittime = {}
        self.needsreset = False

    # A simple utility function to wait for a trigger to fire
    # FIXME: add some checks for handling keyboard input
    # FIXME: using `eval` here might be slow(?) and also means that the user
    # needs to trust the province of their route.json files. Could be improved.
    def triggerwait(self, trigger):
        asi = self.asi
        while not eval(trigger):
            time.sleep(self.timeout)
            self.callback(self.asi, self.activesplits, self.splittime)
            # Should this only run every 0.1 or something?
            if eval(self.route.reset_trigger):
                self.needsreset = True
                return

    def reset(self):
        self.needsreset = False
        self.splittime = {}
        self.activesplits = []
        for split in self.route.splits:
            split[3] = None

    # Watch the list of events, pausing at triggers until the condition is met
    # Calls the print callback every `timeout` seconds
    # FIXME: implement this with an index instead of a loop so that we can impl undo
    def watch(self):
        for event in self.route.events:
            if event[0] == RouteEvent.START_SPLIT:
                self.activesplits.append(event[1])
                self.splittime[event[1]] = self.asi.file_time
            elif event[0] == RouteEvent.END_SPLIT:
                # split[3] stores the elapsed time for completed splits
                time_elapsed = self.asi.file_time - self.splittime[event[1]]
                self.route.splits[event[1]][3] = time_elapsed
                self.activesplits.remove(event[1])
            elif event[0] == RouteEvent.TRIGGER:
                self.triggerwait(event[1])
                if self.needsreset:
                    self.reset()
                    self.watch()
                    return

            self.callback(self.asi, self.activesplits, self.splittime)

# A wrapper around a simple CSV format to handle PB information
#
# format is in the same order as the internal `route.splits` list:
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
            with open(self.filepath, newline="") as f:
                reader = csv.reader(f)
                for line in reader:
                    self.splits.append([line[0], float(line[1]), float(line[2]),
                                       float(line[3]), int(line[4])])
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
        self.pb = sum(self.pb_splits)

        # important: only include top level splits in sum
        self.sum_split_pbs = 0
        self.sum_average_splits = 0
        for i in range(len(self.splits)):
            if self.route.splits[i][1] == 0:
                self.sum_split_pbs += self.split_pbs[i]
                self.sum_average_splits += self.average_splits[i]

    # rewrites the PB file with the latest data after a run
    def update(self, new_splits):
        # if the PB file is empty, we make a new one
        if self.pb == 0:
            self.make_new_pb_file(new_splits)
            return

        # otherwise compare with existing PB times
        total_time = sum([x[3] for x in new_splits])
        for i, newsplit in enumerate(new_splits):
            # update split PB if improved
            if newsplit[1] < self.splits[i][1]:
                self.splits[i][1] = newsplit[3]
            # update PB splits if overall PB
            if total_time < self.pb:
                self.splits[i][2] = newsplit[3]
            # update average splits (unconditionally)
            self.splits[i][3] = ((self.splits[i][3] * self.splits[i][4] + newsplit[3]) /
                                 (self.splits[i][4] + 1))
            # update count (used to calculate averages)
            self.splits[i][4] += 1

        # write to file
        with open(self.filepath, "w", newline="") as f:
            writer = csv.writer(f)
            for row in self.splits:
                writer.writerow(row)

        # update cached values
        self.generate_cached_values()

    # make a new PB file from scratch
    # times for each split are the same since we only have one run
    def make_new_pb_file(self, new_splits):
        with open(self.filepath, "w", newline="") as f:
            writer = csv.writer(f)
            for row in new_splits:
                writer.writerow([row[0], row[3], row[3], row[3], 1])


# The default implementation of a splits printer; allows comparing with a PB
#   file, see `PersonalBest` for implementation.
# Different implementations of this class are possible, e.g. some kind of GUI
# Note that instances of this class are route specific because they require a
# PB instance, which wraps a route specific PB file.
class SplitsPrinter():
    def __init__(self, pb, compare_pb=False, compare_splits=True, compare_average=False):
        self.pb = pb
        self.route = pb.route
        self.compare_pb = compare_pb
        self.compare_splits = compare_splits
        self.compare_average = compare_average

        # this value is prepended to each additional indendation level
        self.padding = "  "

        # split[1] is the indentation, split[2] is the split name
        max_padding = len(self.padding) * max([x[1] for x in pb.route.splits])
        self.max_name_len = max([len(x[2]) for x in pb.route.splits])
        self.max_name_len = max(self.max_name_len, len(pb.route.name))
        self.max_name_len += max_padding

        # generate header
        self.header_text = "Split".ljust(self.max_name_len)
        self.header_text +=     "        Time"
        if self.compare_pb:
            self.header_text += "          PB"
        if self.compare_splits:
            self.header_text += "      Splits"
        if self.compare_average:
            self.header_text += "     Average"
        self.header_text += "\n" + "-" * len(self.header_text)

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
            return f"{hrs}:{mins:02}:{secs:06.3f}"
        if mins > 0:
            return f"{mins}:{secs:06.3f}"
        return f"{secs:.3f}"

    def print(self, asi, activesplits, splittime):
        # this magical string resets the terminal
        print("\x1b\x5b\x48\x1b\x5b\x4a", end="")

        for i, split in enumerate(self.route.splits):
            split_padding = self.padding * split[1]
            fmt_time = ""
            if i in activesplits:
                fmt_time = self.get_hms_from_msecs(asi.file_time - splittime[i])
            elif split[3]:
                fmt_time = self.get_hms_from_msecs(split[3])
            line = f"{(split_padding + split[2]).ljust(self.max_name_len)} {fmt_time.rjust(11)}"
            if self.compare_pb:
                fmt_time = self.get_hms_from_msecs(self.pb.pb_splits[i])
                line += f" {fmt_time.rjust(11)}"
            if self.compare_splits:
                fmt_time = self.get_hms_from_msecs(self.pb.split_pbs[i])
                line += f" {fmt_time.rjust(11)}"
            if self.compare_average:
                fmt_time = self.get_hms_from_msecs(self.pb.average_splits[i])
                line += f" {fmt_time.rjust(11)}"
            print(line)

        # footer containing the time for the whole file
        fmt_time = self.get_hms_from_msecs(asi.file_time)
        line = f"{self.route.name.ljust(self.max_name_len)} {fmt_time.rjust(11)}"
        if self.compare_pb:
            fmt_time = self.get_hms_from_msecs(self.pb.pb)
            line += f" {fmt_time.rjust(11)}"
        if self.compare_splits:
            fmt_time = self.get_hms_from_msecs(self.pb.sum_split_pbs)
            line += f" {fmt_time.rjust(11)}"
        if self.compare_average:
            fmt_time = self.get_hms_from_msecs(self.pb.sum_average_splits)
            line += f" {fmt_time.rjust(11)}"
        print("-" * len(self.header_text))
        print(line)


def main():
    parser = argparse.ArgumentParser(description="A simple Celeste timer with a JSON route format.")
    parser.add_argument("--asi", default="/dev/shm/autosplitterinfo",
                        help="path to the auto splitter file created by the tracer")
    parser.add_argument("--pb", help="path to a custom PB file for the route", default=None)
    parser.add_argument("route", help="path to your route.json file")
    args = parser.parse_args()

    if not args.pb:
        if args.route[-5:] == ".json":
            args.pb = args.route[:-5] + ".pb"
        else:
            args.pb = args.route + ".pb"

    # wait until the tracer is started if necessary
    if not os.path.exists(args.asi):
        print('waiting for', args.asi, '...')
        while not os.path.exists(args.asi):
            time.sleep(1)

    asi = AutoSplitter(args.asi)
    route = JsonRoute(args.route)
    pb = PersonalBest(args.pb, route)
    printer = SplitsPrinter(pb)
    watcher = RouteWatcher(route, asi, printer)
    # FIXME: this should probably keep listening for the reset trigger on completion
    watcher.watch()
    pb.update(route.splits)

if __name__ == '__main__':
    main()
