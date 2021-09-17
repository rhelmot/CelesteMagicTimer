all: celeste_tracer celeste_tracer_loop_mine

clean:
	rm -f celeste_tracer celeste_tracer_loop_mine

celeste_tracer: celeste_tracer.c
	$(CC) -o celeste_tracer $(CFLAGS) celeste_tracer.c -lpthread

celeste_tracer_loop_mine: celeste_tracer_loop_mine.c
	$(CC) -o celeste_tracer_loop_mine $(CFLAGS) celeste_tracer_loop_mine.c
	sudo chown root:root celeste_tracer_loop_mine
	sudo chmod +s celeste_tracer_loop_mine
