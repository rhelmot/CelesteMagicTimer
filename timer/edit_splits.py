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
        route = open_pickle_or_yaml(filename)
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

    pieces, level_names_maybe = edit(pieces)
    if level_names_maybe is not None:
        level_names = level_names_maybe

    route = Route(name, time_field, pieces, level_names, reset_trigger)
    save_yaml(filename, route)

def edit(pieces):
    cursor = len(pieces)
    inhibit = False
    level_names = None
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
                names = [x.strip() for x in ' '.join(args[1:]).split('/')]
                pieces.insert(cursor, Split(names, level=0))
                cursor += 1
            elif args[0] == 'subsplit':
                pieces.insert(cursor, Split([' '.join(args[1:])], level=1))
                cursor += 1
            elif args[0] == 'rename':
                if isinstance(pieces[cursor], Split):
                    names = [x.strip() for x in ' '.join(args[1:]).split('/')]
                    pieces[cursor].names = names
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
            elif args[0] == 'room':
                pieces.insert(cursor, Trigger('Room %s' % args[1], 'asi.level_name == %r' % args[1]))
                cursor += 1
            elif args[0] == 'checkpoint':
                cp = int(args[1])
                pieces.insert(cursor, Trigger('Reach checkpoint %d' % cp, 'asi.chapter_checkpoints == %d' % cp))
                cursor += 1
            elif args[0] == 'kinds':
                level_names = [x.strip() for x in ' '.join(args[1:]).split('/')]

            elif args[0] == 'quit':
                if len(pieces) == 0 or type(pieces[-1]) is not Split or pieces[-1].level != 0:
                    raise TypeError("Last piece of route must be a split")
                return pieces, level_names
            elif args[0] == 'help':
                inhibit = True
                print("""Commands:
- goto <idx>: move your cursor to the given index
- delete: delete the item under your cursor
- split <name>: add a split with the given name
- subsplit <name>: add a subsplit with the given name
- rename <name>: rename the split under the cursor
- overworld: trigger on loading the overworld
- chapter <numberletter>: trigger on entering the given chapter
- room <levelname>: trigger on entering the given room
- checkpoint <number>: trigger on unlocking the given checkpoint (only works in full-game splits)
- complete: trigger on completing the current chapter
- cassette: trigger on collecting the chapter's cassette
- heart: trigger on collecting the chapter's heart
- berries <number>: trigger on reaching n berries
- kinds <name>: name how your "segment" and "subsegment" titles appear, separated by a slash
- quit: save and quit the editor

For the split and rename commands, you can specify a name for the implicit subsplit after a slash (/).

See README.md for a discussion of how splits and triggers work
""")
            else:
                print("Bad command. Type help for help.")
                inhibit = True

        except:  # pylint: disable=bare-except
            traceback.print_exc()
            pieces = rollback
            inhibit = True


if __name__ == '__main__':
    main()
