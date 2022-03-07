#!/usr/bin/env python3

from celeste_timer import *

asi = AutoSplitterInfo()

pieces = []
start_trigger = Trigger('start', 'asi.chapter == %d and asi.mode == %d and asi.chapter_time < 1000' % (asi.chapter, asi.mode))

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
save_yaml(filepath, route)

print('saved to %s' % filepath)
