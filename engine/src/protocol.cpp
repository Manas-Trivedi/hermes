#include <charconv>
#include <cstdint>
#include <vector>
#include <matcha/protocol.hpp>

namespace {

const char *BAD = "ERR BAD_COMMAND\n";
constexpr size_t MAX_FIELDS = 4;

// Splits on single spaces. Empty fields are kept so that doubled, leading and
// trailing spaces are caught as malformed. Returns false on too many fields.
bool split(std::string_view line, std::vector<std::string_view> &fields) {
    size_t start = 0;
    while(true) {
        size_t space = line.find(' ', start);
        if(fields.size() == MAX_FIELDS) return false;
        if(space == std::string_view::npos) {
            fields.push_back(line.substr(start));
            return true;
        }
        fields.push_back(line.substr(start, space - start));
        start = space + 1;
    }
}

// Digits only, fits in 64 bits. from_chars on unsigned already rejects signs.
bool parse_u64(std::string_view s, uint64_t &out) {
    if(s.empty()) return false;
    auto [end, ec] = std::from_chars(s.data(), s.data() + s.size(), out);
    return ec == std::errc() && end == s.data() + s.size();
}

const char *error_name(Status s) {
    switch(s) {
        case Status::Ok: return "OK";
        case Status::DuplicateId: return "DUPLICATE_ID";
        case Status::ArenaFull: return "ARENA_FULL";
        case Status::UnknownId: return "UNKNOWN_ID";
    }
    return "BAD_COMMAND";
}

std::string error_reply(Status s) {
    return std::string("ERR ") + error_name(s) + "\n";
}

std::string trades_reply(const std::vector<Trade> &trades) {
    std::string reply = "OK " + std::to_string(trades.size()) + "\n";
    for(const Trade &t : trades) {
        reply += "TRADE " + std::to_string(t.taker_id) + " " + std::to_string(t.maker_id)
               + " " + std::to_string(t.price) + " " + std::to_string(t.qty) + "\n";
    }
    return reply;
}

std::string book_reply(const OrderBook &book) {
    std::vector<BookEntry> entries;
    book.snapshot(entries);
    std::string reply = "OK " + std::to_string(entries.size()) + "\n";
    for(const BookEntry &e : entries) {
        reply += (e.side == Side::BUY ? "BID " : "ASK ") + std::to_string(e.price)
               + " " + std::to_string(e.qty) + " " + std::to_string(e.id) + "\n";
    }
    return reply;
}

} // namespace

std::string handle_command(OrderBook &book, std::string_view line) {
    if(line.size() > MAX_LINE) return BAD;
    std::vector<std::string_view> f;
    if(!split(line, f)) return BAD;
    const std::string_view cmd = f[0];

    if(cmd == "BOOK") {
        return f.size() == 1 ? book_reply(book) : BAD;
    }
    if(cmd == "CANCEL") {
        uint64_t id;
        if(f.size() != 2 || !parse_u64(f[1], id)) return BAD;
        Status s = book.cancel_order(id);
        return s == Status::Ok ? "OK 0\n" : error_reply(s);
    }

    const bool buy = cmd == "BUY" || cmd == "MBUY";
    const bool sell = cmd == "SELL" || cmd == "MSELL";
    if(!buy && !sell) return BAD;
    const bool market = cmd[0] == 'M';
    if(f.size() != (market ? 3u : 4u)) return BAD;

    Order order;
    order.side = buy ? Side::BUY : Side::SELL;
    order.order_type = market ? OrderType::MARKET : OrderType::LIMIT;
    if(!parse_u64(f[1], order.id) || !parse_u64(f.back(), order.qty) || order.qty == 0) return BAD;
    if(!market && (!parse_u64(f[2], order.price) || order.price == 0)) return BAD;

    std::vector<Trade> trades;
    Status s = book.insert_order(order, trades);
    return s == Status::Ok ? trades_reply(trades) : error_reply(s);
}
