#pragma once
#include <cstdint>
#include <queue>
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
    std::queue<uint64_t> fill_order(Order*);
    bool empty();
    void display_level();
};
