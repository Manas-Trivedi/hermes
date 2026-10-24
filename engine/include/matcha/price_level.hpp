#pragma once
#include <cstdint>
#include <vector>
#include <matcha/order.hpp>

class PriceLevel {
    uint64_t price;
    Order *head;
    Order *tail;
    public:
    PriceLevel(uint64_t p) : price( p ), head( nullptr), tail( nullptr ) {}
    void add_order(Order*);
    void remove_order(Order *);
    void fill_order(Order*, std::vector<Trade>&, std::vector<uint64_t>&);
    bool empty() const;
    void display_level() const;
    void snapshot(Side side, std::vector<BookEntry> &out) const;
};
