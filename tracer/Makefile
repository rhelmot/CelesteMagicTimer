all: celeste_tracer celeste_tracer_loop_mine

clean:
	rm -f celeste_tracer celeste_tracer_loop_mine

celeste_tracer:
	$(CC) -o celeste_tracer celeste_tracer.c -lpthread

celeste_tracer_loop_mine:
	$(CC) -o celeste_tracer_loop_mine celeste_tracer_loop_mine.c
	sudo chown root:root celeste_tracer_loop_mine
	sudo chmod +s celeste_tracer_loop_mine
