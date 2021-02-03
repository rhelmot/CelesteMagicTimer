#!/usr/bin/env python3

# copyright 2021 rhelmot. redistribution is permitted for any purpose provided this copyright notice is kept intact.
# this program comes with absolutely no warranty including fitness for blah blah blah

from celeste_timer import *

asi = AutoSplitterInfo()

pieces = []
start_trigger = Trigger('start', 'asi.chapter == %d and asi.mode == %d and not asi.chapter_started' % (asi.chapter, asi.mode))

print("Go to the room to split on and type the name of the split.")
while not asi.chapter_complete:
    seg_name = input('Segment name: ')
    ctx = 'asi.chapter == %d and asi.mode == %d' % (asi.chapter, asi.mode)
    if asi.chapter_complete:
        trigger = Trigger('done', 'asi.chapter_complete and %s' % ctx)
    else:
        trigger = Trigger('room %s', 'asi.level_name == "%s" and %s' % (asi.level_name, ctx))
    pieces.append(trigger)
    pieces.append(Split(seg_name))

name = input("Route name: ")
filename = input("Filename (will go in ../timer_data/<name>.route): ")

route = Route(name, 'chapter_time', pieces, ['Segment'], start_trigger)
filepath = '../timer_data/%s.route' % filename
with open(filepath, 'wb') as fp:
    pickle.dump(route, fp)

print('saved to %s' % filepath)
