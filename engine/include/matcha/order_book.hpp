#pragma once
#include <cstdint>
#include <map>
#include <queue>
#include <unordered_map>
#include <matcha/order.hpp>
#include <matcha/arena.hpp>
#include <matcha/price_level.hpp>

class OrderBook {
    std::map<uint64_t, PriceLevel> bids;
    std::map<uint64_t, PriceLevel> asks;
    std::unordered_map<uint64_t, Order*> order_lookup;
    Arena arena;
    void drain_filled_orders(std::queue<uint64_t>&);
    void match_order(Order *order);
    public:
    OrderBook(size_t n) : arena(n) {}
    bool contains_order(uint64_t order_id) const;
    const Order* get_order(uint64_t id) const;
    void insert_order(Order &order);
    void cancel_order(uint64_t order_id);
    void display_book();
};
