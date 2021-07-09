#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <getopt.h>
#include <unistd.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include <libgen.h>
#include <dirent.h>
#include <sys/fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/ptrace.h>
#include <sys/wait.h>

#ifdef DEBUG
#define DBGPRINT printf
#else
#define DBGPRINT (void)
#endif

int trace_celeste(const char *celeste_path) {
    int pid = fork();
    if (pid == -1) {
        perror("fork");
        exit(1);
    }

    if (pid == 0) {
        ptrace(PTRACE_TRACEME, 0, 0, 0);
        execl(celeste_path, celeste_path, NULL);
        perror("execl");
        exit(1);
    }

    wait(NULL);
    if (ptrace(PTRACE_CONT, pid, 0, 0) < 0) {
        perror("ptrace continue");
        exit(1);
    }
    return pid;
}

int find_process(const char *needle) {
    char buf[300];
    char path[300];
    DIR *proc = opendir("/proc");
    struct dirent *entry;
    while ((entry = readdir(proc)) != NULL) {
        snprintf(path, sizeof(path), "/proc/%s/exe", entry->d_name);
        ssize_t size = readlink(path, buf, sizeof(buf) - 1);
        if (size < 0) {
            continue;
        }
        buf[size] = 0;
        if (strstr(buf, needle)) {
            return atoi(entry->d_name);
        }
    }
    return 0;
}

int load_mem(int pid) {
    char mempath[100];
    snprintf(mempath, sizeof(mempath), "/proc/%d/mem", pid);

    int fd = open(mempath, O_RDONLY);
    if (fd < 0) {
        perror("open mem");
        exit(1);
    }

    return fd;
}

void read_mem(int fd, uint64_t addr, void *buf, size_t len) {
    if (lseek(fd, addr, SEEK_SET) == -1) {
        perror("lseek");
        exit(1);
    }

    if (read(fd, buf, len) != (ssize_t)len) {
        perror("read");
        exit(1);
    }
}

uint64_t read_qword(int fd, uint64_t addr) {
    uint64_t out;
    read_mem(fd, addr, &out, sizeof(out));
    return out;
}

uint32_t read_dword(int fd, uint64_t addr) {
    uint32_t out;
    read_mem(fd, addr, &out, sizeof(out));
    return out;
}

uint16_t read_word(int fd, uint64_t addr) {
    uint16_t out;
    read_mem(fd, addr, &out, sizeof(out));
    return out;
}

uint8_t read_byte(int fd, uint64_t addr) {
    uint8_t out;
    read_mem(fd, addr, &out, sizeof(out));
    return out;
}

char *read_string(int fd, uint64_t addr) {
    char *out = malloc(0x100);
    read_mem(fd, addr, out, 0x100);
    out[0xff] = 0;
    return out;
}

char *class_name(int memfd, uint64_t klass) {
    uint64_t name_ptr = read_qword(memfd, klass + 0x40);
    return read_string(memfd, name_ptr);
}


uint64_t celeste_image, celeste_class_cache;

uint64_t lookup_class(int memfd, char *name) {
    uint64_t celeste_class_cache_table = read_qword(memfd, celeste_class_cache + 0x20);
    uint32_t hash_table_size = read_dword(memfd, celeste_class_cache + 0x18);
    for (uint32_t bucket = 0; bucket < hash_table_size; bucket++) {
        uint64_t klass = read_qword(memfd, celeste_class_cache_table + 8*bucket);
        while (klass != 0) {
            char *current_name = class_name(memfd, klass);
            if (strcmp(name, current_name) == 0) {
                free(current_name);
                return klass;
            }
            free(current_name);
            klass = read_qword(memfd, klass + 0xf8);
        }
    }
    printf("Could not find class %s\n", name);
    exit(1);
}

uint64_t class_static_fields(int memfd, uint64_t klass) {
    uint32_t vtable_size = read_dword(memfd, klass + 0x54);
    uint64_t runtime_info = read_qword(memfd, klass + 0xc8);
    // hack: assume the class is only valid in one domain
    uint64_t max_domains = read_qword(memfd, runtime_info);
    for (int i = 0; i <= (int)max_domains; i++) {
        uint64_t vtable = read_qword(memfd, runtime_info + 8 + 8*i);
        if (vtable != 0) {
            return read_qword(memfd, vtable + 64 + 8*vtable_size);
        }
    }
    puts("No domain has this class loaded");
    exit(1);
}

uint64_t instance_class(int memfd, uint64_t instance) {
    return read_qword(memfd, read_qword(memfd, instance) & ~1);
}

typedef struct _MonoClassField {
	uint64_t type; 
	uint64_t name;
        uint64_t parent;
	uint32_t offset;
} MonoClassField;

typedef enum {
	MONO_CLASS_DEF = 1, /* non-generic type */
	MONO_CLASS_GTD, /* generic type definition */
	MONO_CLASS_GINST, /* generic instantiation */
	MONO_CLASS_GPARAM, /* generic parameter */
	MONO_CLASS_ARRAY, /* vector or array, bounded or not */
	MONO_CLASS_POINTER, /* pointer of function pointer*/
} MonoTypeKind;

MonoTypeKind class_kind(int memfd, uint64_t klass) {
    return (MonoTypeKind)read_byte(memfd, klass + 0x24) & 7;
}

// For getters with implicit storage it's <Name>k__BackingField WITH the braces
uint32_t class_field_offset(int memfd, uint64_t klass, char *name) {
    MonoTypeKind kind = class_kind(memfd, klass);
    if (kind == MONO_CLASS_GINST) {
        return class_field_offset(memfd, read_qword(memfd, read_qword(memfd, klass + 0xe0)), name);
    }
    if (kind != MONO_CLASS_DEF && kind != MONO_CLASS_GTD) {
        puts("Something is wrong");
        exit(1);
    }
    size_t namesize = strlen(name);
    uint32_t num_fields = read_dword(memfd, klass + 0xf0);
    uint64_t fields_ptr = read_qword(memfd, klass + 0x90);
    MonoClassField fields[num_fields];
    char nametest[namesize + 1];

    read_mem(memfd, fields_ptr, fields, sizeof(fields));
    for (uint32_t i = 0; i < num_fields; i++) {
        read_mem(memfd, fields[i].name, nametest, sizeof(nametest));
        if (nametest[namesize] != 0) {
            continue;
        }
        if (strcmp(name, nametest) == 0) {
            return fields[i].offset;
        }
    }
    printf("Tried to lookup nonexistent field: %s\n", name);
    exit(1);
}

uint64_t instance_field_qword(int memfd, uint64_t instance, char *name) {
    uint64_t klass = instance_class(memfd, instance);
    uint32_t field_offset = class_field_offset(memfd, klass, name);
    return read_qword(memfd, instance + field_offset);
}

uint64_t instance_field_dword(int memfd, uint64_t instance, char *name) {
    uint64_t klass = instance_class(memfd, instance);
    uint32_t field_offset = class_field_offset(memfd, klass, name);
    return read_dword(memfd, instance + field_offset);
}

uint8_t instance_field_byte(int memfd, uint64_t instance, char *name) {
    uint64_t klass = instance_class(memfd, instance);
    uint32_t field_offset = class_field_offset(memfd, klass, name);
    return read_byte(memfd, instance + field_offset);
}

uint64_t static_field_qword(int memfd, uint64_t klass, char *name) {
    uint64_t static_data = class_static_fields(memfd, klass);
    uint32_t field_offset = class_field_offset(memfd, klass, name);
    return read_qword(memfd, static_data + field_offset);
}

uint64_t static_field_dword(int memfd, uint64_t klass, char *name) {
    uint64_t static_data = class_static_fields(memfd, klass);
    uint32_t field_offset = class_field_offset(memfd, klass, name);
    return read_dword(memfd, static_data + field_offset);
}

char *read_boxed_string_chars(int memfd, uint64_t instance) {
    uint64_t klass = instance_class(memfd, instance);
    uint32_t data_offset = class_field_offset(memfd, klass, "m_firstChar");
    uint32_t size_offset = class_field_offset(memfd, klass, "m_stringLength");
    uint32_t size = read_dword(memfd, instance + size_offset);
    short *wordres = malloc(size * 2);
    char *charres = malloc(size + 1);
    read_mem(memfd, instance + data_offset, wordres, size*2);
    for (uint32_t i = 0; i < size; i++) {
        charres[i] = wordres[i];
    }
    charres[size] = 0;
    free(wordres);
    return charres;
}

uint64_t savedata_class, celeste_class, celeste_instance, engine_class, level_class;

void load_base_info(int memfd) {
    uint64_t root_domain = read_qword(memfd, 0xA17650); // mono_root_domain
    uint64_t domains_list = read_qword(memfd, 0xA17698); // appdomains_list
    uint64_t celeste_domain;
    uint64_t first_domain = read_qword(memfd, domains_list);
    uint64_t second_domain = read_qword(memfd, domains_list + 8);
    char *first_domain_name = first_domain == 0 ? 0 : read_string(memfd, read_qword(memfd, first_domain + 0xd8));
    char *second_domain_name = second_domain == 0 ? 0 : read_string(memfd, read_qword(memfd, second_domain + 0xd8));

    if (first_domain_name == 0 || strcmp(first_domain_name, "Celeste.exe") != 0) {
        puts(first_domain_name);
        puts("This is not a celeste! (or maybe just not initialized)");
        exit(1);
    }

    if (second_domain != 0) {
        printf("Connected to %s\n", second_domain_name);
        celeste_domain = second_domain;
    } else {
        printf("Connected to %s\n", first_domain_name);
        celeste_domain = first_domain;
    }

    uint64_t celeste_assembly = read_qword(memfd, celeste_domain + 0xd0);
    celeste_image = read_qword(memfd, celeste_assembly + 0x60);
    celeste_class_cache = celeste_image + 1216;
    celeste_class = lookup_class(memfd, "Celeste");
    savedata_class = lookup_class(memfd, "SaveData");
    engine_class = lookup_class(memfd, "Engine");
    level_class = lookup_class(memfd, "Level");
    celeste_instance = static_field_qword(memfd, celeste_class, "Instance");
}

uint64_t locate_autosplitter_info(int memfd) {
    uint64_t autosplitter_instance = instance_field_qword(memfd, celeste_instance, "AutoSplitterInfo");
    return autosplitter_instance + 0x10;
}

struct marshall {
    int memfd;
    const char *filename;
};

typedef struct _AutoSplitterInfo {
    uint64_t Level;
    int Chapter;
    int Mode;
    bool TimerActive;
    bool ChapterStarted;
    bool ChapterComplete;
    long ChapterTime;
    int ChapterStrawberries;
    bool ChapterCassette;
    bool ChapterHeart;
    long FileTime;
    int FileStrawberries;
    int FileCassettes;
    int FileHearts;
} AutoSplitterInfo;

typedef struct _DumpInfo {
    AutoSplitterInfo asi;
    int CurrentLevelCheckpoints;
    bool InCutscene;
    int DeathCount;
    char LevelName[100];
} DumpInfo;

void *dump_info_loop(void *v) {
    struct marshall *m = (struct marshall *)v;
    int memfd = m->memfd;
    const char *filename = m->filename;

    sleep(2);
    unlink(filename);
    int fifo = mkfifo(filename, 0644);
    if (fifo < 0) {
        perror("could not create fifo");
        exit(1);
    }
    int dumpfd = open(filename, O_RDWR);
    if (dumpfd < 0) {
        perror("open info dump file");
        exit(1);
    }
    load_base_info(memfd);
    uint64_t info_addr = locate_autosplitter_info(memfd);
    DBGPRINT("ASI @ %p\n", info_addr);
    uint64_t savedata_addr = 0;
    uint64_t mode_stats = 0;

    DumpInfo info_buf;
    memset(&info_buf, 0, sizeof(DumpInfo));
    uint64_t areas_obj;
    uint64_t last_savedata_addr = 0;
    uint64_t last_level = 0;
    uint64_t last_scene = 0;
    while (1) {
        struct timespec millisecond = {0, 1000000};
        nanosleep(&millisecond, NULL);
        // Extract ASI
        read_mem(memfd, info_addr, &info_buf.asi, sizeof(AutoSplitterInfo));
        DBGPRINT("chapter = %d, mode = %d\n", info_buf.asi.Chapter, info_buf.asi.Mode);

        // Extract ASI.Level
        if (info_buf.asi.Level != 0) {
            char *lvlname = read_boxed_string_chars(memfd, info_buf.asi.Level);
            strncpy(info_buf.LevelName, lvlname, sizeof(info_buf.LevelName));
            free(lvlname);
        } else {
            strncpy(info_buf.LevelName, "", sizeof(info_buf.LevelName));
        }

        savedata_addr = static_field_qword(memfd, savedata_class, "Instance");
        DBGPRINT("savedata_addr = %p\n", (void*)savedata_addr);
        if (savedata_addr != 0) {
            if (savedata_addr != last_savedata_addr) {
                sleep(1);
                last_savedata_addr = savedata_addr;
                mode_stats = 0;
                continue;
            }
            // extract death count
            info_buf.DeathCount = instance_field_dword(memfd, savedata_addr, "TotalDeaths");

            // Extract checkpoint count
            if (info_buf.asi.Chapter == -1) {
                mode_stats = 0;
            } else if (mode_stats == 0) {
                areas_obj = instance_field_qword(memfd, savedata_addr, "Areas");
                uint64_t areas_arr;
                if (instance_field_dword(memfd, areas_obj, "_size") == 11) {
                    DBGPRINT("Passed\n");
                    areas_arr = instance_field_qword(memfd, areas_obj, "_items");
                    DBGPRINT("areas_arr = %p\n", (void*)areas_arr);
                } else {
                    DBGPRINT("Failed\n");
                    areas_arr = 0;
                }

                if (areas_arr != 0) {
                    uint64_t area_stats = read_qword(memfd, areas_arr + 0x20 + info_buf.asi.Chapter*8);
                    DBGPRINT("area_stats = %p\n", (void*)area_stats);
                    uint64_t mode_arr = instance_field_qword(memfd, area_stats, "Modes") + 0x20;
                    DBGPRINT("mode_arr = %p\n", (void*)mode_arr);
                    mode_stats = read_qword(memfd, mode_arr + info_buf.asi.Mode*8);
                }
            }
            DBGPRINT("mode_stats = %p\n", (void*)mode_stats);

            if (mode_stats != 0) {
                uint64_t checkpoints_obj = instance_field_qword(memfd, mode_stats, "Checkpoints");
                DBGPRINT("checkpoints_obj = %p\n", (void*)checkpoints_obj);
                info_buf.CurrentLevelCheckpoints = instance_field_dword(memfd, checkpoints_obj, "_count");
                DBGPRINT("CurrentLevelCheckpoints = %d\n", info_buf.CurrentLevelCheckpoints);
            } else {
                info_buf.CurrentLevelCheckpoints = 0;
            }
        }

        // Extract in-cutscene
        if (info_buf.asi.Chapter != -1) {
            if (!info_buf.asi.ChapterStarted || info_buf.asi.ChapterComplete) {
                info_buf.InCutscene = true;
            } else {
                uint64_t scene = read_qword(memfd, celeste_instance + class_field_offset(memfd, engine_class, "scene"));
                if (instance_class(memfd, scene) != level_class) {
                    info_buf.InCutscene = false;
                } else {
                    info_buf.InCutscene = read_byte(memfd, scene + class_field_offset(memfd, level_class, "InCutscene"));
                }
            }
        } else {
            info_buf.InCutscene = false;
        }

        lseek(dumpfd, 0, SEEK_SET);
        write(dumpfd, &info_buf, sizeof(DumpInfo));
    }
}

pthread_t thread;
void dump_info_thread(int memfd, const char *filename) {
    struct marshall *m = malloc(sizeof(struct marshall));
    m->memfd = memfd;
    m->filename = filename;
    pthread_create(&thread, NULL, dump_info_loop, m);
}


void *wait_cont_loop(int pid) {
    int winfo;
    while (1) {
        wait(&winfo);
        if (!WIFSTOPPED(winfo)) {
            if (WIFEXITED(winfo)) {
                exit(0);
            }
            if (WIFSIGNALED(winfo) && WTERMSIG(winfo) == SIGABRT) {
                printf("Crash loop\n");
                exit(6);
            }
            printf("idk what to do with this\n");
            exit(1);
        }
        ptrace(PTRACE_CONT, pid, 0, WSTOPSIG(winfo));
    }
}

void usage(char *argv0) {
    printf("Usage: %s --dump <asi path> --launch <celeste path>\n"
           "OR     sudo %s --dump <asi path> --attach\n",
           argv0, argv0);
}

int main(int argc, char **argv) {
    srand(time(0));
    bool okay = false;
    char *celeste_path = NULL;
    char *asi_path = NULL;
    int c, option_index;

    while (1) {
        static struct option long_options[] = {
            {"launch", required_argument, 0, 0 },
            {"attach", no_argument, 0, 0},
            {"dump", required_argument, 0, 0},
        };

        c = getopt_long(argc, argv, "", long_options, &option_index);
        if (c == -1) {
            break;
        } else if (c != 0) {
            usage(argv[0]);
            exit(1);
        }

        switch (option_index) {
            case 0:
                okay = true;
                // hack: fix the basename to point to mono
                char *celeste_basename = basename(optarg);
                char *celeste_dirname = dirname(optarg);
                if (strcmp(celeste_basename, "Celeste") == 0 || strcmp(celeste_basename, "Celeste.exe") == 0) {
                    celeste_basename = "Celeste.bin.x86_64";
                }

                celeste_path = malloc(strlen(celeste_dirname) + strlen(celeste_basename) + 5);
                strcpy(celeste_path, "");
                strcat(celeste_path, celeste_dirname);
                strcat(celeste_path, "/");
                strcat(celeste_path, celeste_basename);
                break;
            case 1:
                okay = true;
                celeste_path = NULL;
                break;
            case 2:
                asi_path = optarg;
                break;
        }

    }

    if (!okay || asi_path == NULL) {
        usage(argv[0]);
        exit(1);
    }

    if (celeste_path != NULL) {
        int celeste = trace_celeste(celeste_path);
        int memfd = load_mem(celeste);

        dump_info_thread(memfd, asi_path);
        wait_cont_loop(celeste);
    } else {
        int celeste = find_process("Celeste.bin.x86_64");
        if (celeste == 0) {
            puts("Could not find celeste");
            exit(1);
        }
        int memfd = load_mem(celeste);

        dump_info_thread(memfd, asi_path);
        while (1) { sleep(1); }
    }
}

// set $root_domain = (void*)mono_root_domain
// set $assemblies_list = *(void**)($root_domain + 200)
// set $assemblies_list_2 = *(void**)($assemblies_list + 8)
// set $celeste_assembly = *(void**)($assemblies_list_2)
// set $celeste_assembly_name = *(char**)($celeste_assembly + 0x10)
// set $celeste_image = *(void**)($celeste_assembly + 0x60)
// set $celeste_image_is_dynamic = (*(unsigned char *)($celeste_image + 0x1C) >> 3) & 1
// set $celeste_class_cache = ($celeste_image + 1216)
// set $hash_table_size = *(int*)($celeste_class_cache + 0x18)
// set $celeste_bucket = 0x200033c % $hash_table_size
// set $celeste_class_cache_table = *(void***)($celeste_class_cache + 0x20)
// set $celeste_class = $celeste_class_cache_table[$celeste_bucket]
// set $celeste_fake_vtable = *(void***)($celeste_class + 0xd0)
// set $celeste_class_token = *(int*)($celeste_class + 0x50)
// set $celeste_class_next = *(void**)($celeste_class + 0xf8)
// set $celeste_field_list = *(void**)($celeste_class + 0x90)
// set $celeste_vtable_size = *(int*)($celeste_class + 0x54)
// set $celeste_runtime_info = *(void**)($celeste_class + 0xc8)
// set $celeste_vtable = *(void**)($celeste_runtime_info + 8)
// set $celeste_static_fields = *(void**)($celeste_vtable + 64 + 8*$celeste_vtable_size)
// set $celeste_obj = *(void**)($celeste_static_fields + 8)
// set $autosplitter_obj = *(void**)($celeste_obj + 0xf8)
// set $savedata_bucket = 0x20002d8 % $hash_table_size
// set $savedata_class = $celeste_class_cache_table[$savedata_bucket]
// set $savedata_fake_vtable = *(void***)($savedata_class + 0xd0)
// set $savedata_class_token = *(int*)($savedata_class + 0x50)
// set $savedata_class_next = *(void**)($savedata_class + 0xf8)
// set $savedata_field_list = *(void**)($savedata_class + 0x90)
// set $savedata_vtable_size = *(int*)($savedata_class + 0x54)
// set $savedata_runtime_info = *(void**)($savedata_class + 0xc8)
// set $savedata_vtable = *(void**)($savedata_runtime_info + 8)
// set $savedata_static_fields = *(void**)($savedata_vtable + 64 + 8*$savedata_vtable_size)
// set $savedata_instance = *(void**)($savedata_static_fields)
// set $areas_instance = *(void**)($savedata_instance + 0x48)
// set $areas_class = **(void***)($areas_instance)
// set $areas_baseclass = **(void***)($areas_class + 0xe0)
// set $areas_field_list = *(void**)($areas_class + 0x90)
// set $areas_items = *(void**)($areas_instance + 0x10)
// set $area_2_instance = *(void **)($areas_items + 0x20 + 2*8)
// set $area_2_class = **(void***)($area_2_instance)
// set $area_2_field_list = *(void**)($area_2_class + 0x90)
// set $area_2_modes = *(void**)($area_2_instance + 0x10)
// set $area_2_mode_0_instance = *(void**)($area_2_modes + 0x20 + 0*8)
// set $area_2_mode_0_class = **(void***)($area_2_mode_0_instance)
// set $area_2_mode_0_field_list = *(void**)($area_2_mode_0_class + 0x90)
// set $old_site_checkpoints_instance = *(void**)($area_2_mode_0_instance + 0x18)
// set $old_site_checkpoints_class = **(void***)($old_site_checkpoints_instance)
// set $old_site_checkpoints_field_list = *(void**)($old_site_checkpoints_class + 0x90)
// set $old_site_checkpoints_count = *(int*)($old_site_checkpoints_instance + 0x30)
