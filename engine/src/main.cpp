#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <matcha/protocol.hpp>

// Reads one line, keeping at most MAX_LINE + 1 bytes and discarding the rest,
// so an over-long line costs bounded memory. handle_command rejects the
// MAX_LINE + 1 byte remainder as too long. Returns false at EOF.
static bool read_line(std::string &line) {
    line.clear();
    bool any = false;
    int c;
    while((c = std::cin.get()) != EOF) {
        any = true;
        if(c == '\n') return true;
        if(line.size() <= MAX_LINE) line.push_back(static_cast<char>(c));
    }
    return any;
}

int main(int argc, char **argv) {
    char *end = nullptr;
    unsigned long long arena = 0;
    if(argc == 3 && std::strcmp(argv[1], "--arena") == 0) arena = std::strtoull(argv[2], &end, 10);
    if(arena == 0 || !end || *end != '\0') {
        std::fprintf(stderr, "usage: matcha --arena <max resting orders>\n");
        return 2;
    }

    OrderBook book(arena);
    std::cout << "READY\n" << std::flush;

    std::string line;
    while(read_line(line)) {
        // flush every reply: the client blocks until it arrives
        std::cout << handle_command(book, line) << std::flush;
    }
    return 0;
}
