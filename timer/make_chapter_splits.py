from celeste_timer import *

chapter_names = [
        'Prologue', 'City', 'Site', 'Resort', 'Ridge', 'Temple',
        'Reflection', 'Summit', 'Core', 'Farewell'
]

pieces = []
start_trigger = Trigger('start', 'asi.chapter == 0 and 0 < asi.file_time < 1000')
print('Type in the list of chapters you will be *completing* during the run, one per line.')
print('For example, "1a"')
print('To indicate the end of the list, end your last chapter with an exclamation point')
print('For example, "7a!"')
print('(prologue is 0a and farewell is 9a)')
while True:
    line = input('> ')
    assert len(line) >= 2
    end = line[-1] == '!'
    if end:
        line = line[:-1]
    line, side = line[:-1], line[-1]
    side = side.lower()
    assert side in ('a', 'b', 'c')
    mode = ord(side) - ord('a')
    chapter = int(line)
    if chapter >= 8:
        chapter += 1
    pieces.append(Trigger('finish %s%s' % (line, side), 'asi.chapter == %d and asi.mode == %d and asi.chapter_complete' % (chapter, mode)))
    pieces.append(Trigger('exit chapter', 'asi.chapter == -1'))
    pieces.append(Split(['%s%s' % (chapter_names[int(line)], (' ' + side.upper()) if chapter not in (0, 10) else '')], 0))

    if end:
        break

name = input("Route name: ")
filename = input("Filename (will go in ../timer_data/<name>.route): ")

route = Route(name, 'file_time', pieces, ['Chapter'], start_trigger)
filepath = '../timer_data/%s.route' % filename
save_yaml(filepath, route)

print('saved to %s' % filepath)
