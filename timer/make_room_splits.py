from celeste_timer import *

asi = AutoSplitterInfo()

input("Go to the start of the chapter you want to set up room splits for and press enter: ")

current_room = asi.level_name
ctx = 'asi.chapter == %d and asi.mode == %d' % (asi.chapter, asi.mode)
pieces = []
seen_rooms = {current_room}
start_trigger = Trigger('start', '%s and asi.chapter_time < 1000' % ctx)

print("Now, please play through the level")

while not asi.chapter_complete:
    if asi.level_name not in seen_rooms:
        trigger = Trigger('enter %s' % asi.level_name, 'asi.level_name == "%s" and %s' % (asi.level_name, ctx))
        split = Split(current_room)
        current_room = asi.level_name

        pieces.append(trigger)
        pieces.append(split)
        seen_rooms.add(current_room)
    time.sleep(0.05)

trigger = Trigger('done', 'asi.chapter_complete and %s' % ctx)
split = Split(current_room)
pieces.append(trigger)
pieces.append(split)


name = input("Route name: ")
filename = input("Filename (will go in ../timer_data/<name>.route): ")

route = Route(name, 'chapter_time', pieces, ['Segment'], start_trigger)
filepath = '../timer_data/%s.route' % filename
save_yaml(filepath, route)

print('saved to %s' % filepath)
