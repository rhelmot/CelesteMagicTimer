#!/usr/bin/env python3
import uuid
from celeste_timer import *

class RoomSplitsMaker:
    def __init__(self) -> None:
        self.asi = None
        self.current_room = None
        self.ctx = None
        self.pieces = None
        self.seen_rooms = None
        self.start_trigger = None
        
    def setup_split_maker(self):
        self.asi = AutoSplitterInfo()
        self.current_room = self.asi.level_name
        self.ctx = 'asi.chapter == %d and asi.mode == %d' % (self.asi.chapter, self.asi.mode)
        self.pieces = []
        self.seen_rooms = {self.current_room}
        self.start_trigger = Trigger('start', '%s and asi.chapter_time < 1000' % self.ctx)


    def wait_for_playthrough(self):
        while not self.asi.chapter_complete:
            if self.asi.level_name not in self.seen_rooms:
                trigger = Trigger('enter %s' % self.asi.level_name, 'asi.level_name == "%s" and %s' % (self.asi.level_name, self.ctx))
                split = Split(self.current_room)
                self.current_room = self.asi.level_name

                self.pieces.append(trigger)
                self.pieces.append(split)
                self.seen_rooms.add(self.current_room)
            time.sleep(0.05)
        trigger = Trigger('done', 'asi.chapter_complete and %s' % self.ctx)
        split = Split(self.current_room)
        self.pieces.append(trigger)
        self.pieces.append(split)

    def save_route(self, file_name=None, route_name=None, customPath=None):
        if file_name is None:
            filename = str(uuid.uuid4())
        else:
            filename = file_name

        if route_name is None:
            name = filename
        else:
            name = route_name
            
        route = Route(name, 'chapter_time', self.pieces, ['Segment'], self.start_trigger)
        if customPath is None:
            filepath = '../timer_data/%s.route' % filename
        else:
            filepath  = customPath
            
        save_yaml(filepath, route)
        print('saved to %s' % filepath)

if __name__ == '__main__':
    maker = RoomSplitsMaker()
    input("Go to the start of the chapter you want to set up room splits for and press enter: ")
    maker.setup_split_maker()
    print("Now, please play through the level")
    maker.wait_for_playthrough()
    name = input("Route name: ")
    filename = ifilename = input("Filename (will go in ../timer_data/<name>.route): ")
    maker.save_route(route_name=name, file_name=filename)
