DESTDIR=
PREFIX=/usr

all: tracer/celeste_tracer

tracer/celeste_tracer:
	$(MAKE) -C tracer/ celeste_tracer

install: all
	mkdir -p $(DESTDIR)$(PREFIX)/bin
	install -m755 tracer/celeste_tracer $(DESTDIR)$(PREFIX)/bin

.PHONY: install all
