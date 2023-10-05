import time
from collections import defaultdict
from .celeste_timer import AutoSplitterInfo

asi = AutoSplitterInfo()

seen_deaths = None
deaths = None

def reset():
    global deaths, seen_deaths
    deaths = defaultdict(list)
    seen_deaths = asi.death_count

def update():
    global seen_deaths
    if asi.chapter == 0 and 1 < asi.file_time < 1000:
        reset()
    while asi.death_count > seen_deaths and asi.death_count < seen_deaths + 5:
        death()

def death():
    global seen_deaths
    seen_deaths += 1
    deaths[asi.chapter_name].append(asi.level_name)

def render(maximum=5):
    out = ['Deaths:', '']

    for chapter in deaths:
        lst = deaths[chapter]
        if lst:
            prefix = ', '.join(lst[:maximum])
            suffix = '' if len(lst) <= maximum else ' + %d more' % (len(lst) - maximum)
            out.append('%s: %s%s' % (chapter, prefix, suffix))

    print('\x1b\x5b\x48\x1b\x5b\x4a' + '\n'.join(out))

try:
    time.sleep(0.5)
    reset()
    while True:
        time.sleep(0.1)
        update()
        render()
except KeyboardInterrupt:
    pass
render(999999999)
