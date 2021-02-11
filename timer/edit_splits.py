#!/usr/bin/env python3

import sys
import pickle
import traceback

from celeste_timer import *  # pylint: disable=wildcard-import,unused-wildcard-import

def main():
    if len(sys.argv) != 2:
        print('Usage: edit_splits.py [route filename]')
    filename = sys.argv[1]
    try:
        with open(filename, 'rb') as fp:
            route = pickle.load(fp)
            pieces = list(route)
            name = route.name
            time_field = route.time_field
            level_names = route.level_names
            reset_trigger = route.reset_trigger
    except FileNotFoundError:
        pieces = []
        name = input('Route name: ')
        if 'file' in input('Chapter or file time: ').lower():
            time_field = 'file_time'
            reset_trigger = Trigger('Start prologue', 'asi.chapter == 0 and asi.file_time < 1000')
        else:
            time_field = 'chapter_time'
            chapter, mode = parse_mapname(input('Chapter: '))
            reset_trigger = Trigger('Start chapter', 'asi.chapter == %d and asi.mode == %d and asi.chapter_time < 1000' % (chapter, mode))
        level_names = ['Split', 'Subsplit', 'Subsubsplit']

    pieces = edit(pieces)

    route = Route(name, time_field, pieces, level_names, reset_trigger)
    with open(filename, 'wb') as fp:
        pickle.dump(route, fp)

def edit(pieces):
    cursor = len(pieces)
    inhibit = False
    while True:
        if not inhibit:
            for i, piece in enumerate(pieces + ['']):
                prefix = '->' if i == cursor else '  '
                print('%s %02d. %s' % (prefix, i + 1, piece))
        else:
            inhibit = False

        cmd = input('> ')
        args = cmd.split()
        rollback = list(pieces)
        try:
            if args[0] == 'goto':
                idx = int(args[1]) - 1
                if not 0 <= idx <= len(pieces):
                    raise ValueError("Bad index")
                cursor = idx
            elif args[0] == 'delete':
                pieces.pop(cursor)
            elif args[0] == 'split':
                pieces.insert(cursor, Split([' '.join(args[1:])]))
                cursor += 1
            elif args[0] == 'rename':
                if isinstance(pieces[cursor], Split):
                    pieces[cursor].names[0] = ' '.join(args[1:])
                else:
                    pieces[cursor].name = ' '.join(args[1:])
            elif args[0] == 'overworld':
                pieces.insert(cursor, Trigger('Return to map', 'asi.chapter == -1'))
                cursor += 1
            elif args[0] == 'chapter':
                chapter, mode = parse_mapname(args[1])
                pieces.insert(cursor, Trigger('Enter %s' % args[1], 'asi.chapter == %d and asi.mode == %d' % (chapter, mode)))
                cursor += 1
            elif args[0] == 'complete':
                pieces.insert(cursor, Trigger("Chapter complete", 'asi.chapter_complete'))
                cursor += 1
            elif args[0] == 'cassette':
                pieces.insert(cursor, Trigger('Get cassette', 'asi.chapter_cassette'))
                cursor += 1
            elif args[0] == 'heart':
                pieces.insert(cursor, Trigger('Get heart', 'asi.chapter_heart'))
                cursor += 1
            elif args[0] == 'berries':
                berries = int(args[1])
                pieces.insert(cursor, Trigger('%d berries' % berries, 'asi.file_strawberries == %d' % berries))
                cursor += 1
            elif args[0] == 'quit':
                if len(pieces) == 0 or type(pieces[-1]) is not Split or pieces[-1].level != 0:
                    raise TypeError("Last piece of route must be a split")
                return pieces
            elif args[0] == 'help':
                inhibit = True
                print("Commands: goto <idx>, delete, split <name>, rename <name>, overworld, chapter <numberletter>, complete, cassette, heart, berries <number>, quit")
            else:
                print("Bad command. Type help for help.")
                inhibit = True

        except:  # pylint: disable=bare-except
            traceback.print_exc()
            pieces = rollback
            inhibit = True


if __name__ == '__main__':
    main()
