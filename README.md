rhelmot's Celeste Magic Timer
=============================

This is an autosplitter for Celeste on Linux, working on all versions and also with Everest installed. I guess it could theoretically be made to work on other games but why would you do that?

**This is a complicated piece of software!** I am more than happy to help anyone who wants to use this learn this. There's a lot you can do with this program once you really know what you're doing.

The Tracer
----------

The first component of the setup is the tracer. This is a program which reads Celeste's memory and dumps out information about the game state to a file, by default `/dev/shm/autosplitterinfo`. You can build it by typing `make` in the `tracer` folder.

The tracer can operate in two modes - one where it launches Celeste itself and thus does not require elevated privileges, and one where you launch it as root and it attaches to the Celeste process. These, along with the path where you want the autosplitter data dumped, are specified on the command line.

The way I've set it up is to have a loop always running in the background which is constantly trying to connect to any running Celeste instances. In order to do this securely, I've put the relevant paths in `celeste_tracer_loop_mine.c` and compiled it as a setuid binary - this means that it can be easily run with root privilege on login if you change the paths in the C source to work correctly on your computer.

### How does it work?

Crawling the mono data structures. It's amazing; please don't ask.

The Timer
---------

The `timer` folder contains python scripts that read the autosplitter info file and track splits. In order to use them, you'll need the dependencies from `requirements.txt` in the repository root: `pip3 install --user -r requirements.txt`. You can run the scripts with python3, e.g. `python3 celeste_timer.py`.

The most basic file is `celeste_timer.py`, which simply formats the data to text on the screen. This is useful for verifying that the tracer is working. This file is also a library which provides to the other scripts the ability to access this data, and also some primitives for manipulating splits.

The next-most important script is `full_splits.py`. This is a standard autosplitter program. It takes as input a path to a route file (a yaml dump which contains a `celeste_timer.Route` object serialized via pyyaml), and tracks your pb and gold splits. It uses the convention that routes should be stored in `timer_data/<name>.route` (I've provided a sample anypercent.route), pb data should be stored in `timer_data/<name>.pb`, and gold split data should be stored in `timer_data/<name>.best`. The timer will show you desktop notifications for split status and has keyboard shortcuts for resetting and skipping forward and backwards.

The next-most important script is `edit_splits.py`. This should allow you to create and open route files for editing.

The next-most important scripts are the `make_*_splits.py` files. These are programs which interactively construct a route file for you with some common templates.

Finally, we have `stream.py`, which is another autosplitter program which formats its data in a stream-friendly format. This one has much better coding standards, and should be used as a base if you want to write your own display program.

The Route Format
----------------

When using `edit_splits.py`, you are given the ability to create a sequence of "triggers" and "splits". During gameplay, the autosplitter keeps track of where in this sequence you are, starting at the beginning and proceeding past each trigger when its condition is met. Whenever you pass a split, the autosplitter will split. The display will show you the splits, but not the triggers.

When using subsplits, it's important to keep in mind that top level splits also serve as subsplits if they are preceded by a subsplit. For example, if you have the following route:

```
...
Ridge A
  Start
  Shrine
  Old Trail
  Cliff Face
Temple A
   ....
```

Your route file will look like the following:

```
...
- Trigger to indicate Start was completed
- Subsplit Start
- Trigger to indicate Shrine was completed
- Subsplit Shrine
- Trigger to indicate Old Trail was completed
- Subsplit Old Trail
- Trigger to indicate Cliff Face was completed
- Split Ridge A/Cliff Face
...
```

Since there are only splits wherever the autosplitter should actually split, and when you finish a split with subsplits you are capturing two different levels of timing at once, the final split in this sequence serves as both a subsplit and a normal split. When editing this split with `edit_splits.py`, you can put a slash in the name of the split to indicate that it has two names, first for the top level split and then for the subsplit.

Contributing
------------

If you want to help out with this project, thank you!!! Feel free to submit pull requests for whatever you want and I'll review them. If you want suggestions for what kind of projects to work on, you can check out any of the open issues in the github Issues tab. Additionally, feel free to open issues asking for help understanding how the code works.
