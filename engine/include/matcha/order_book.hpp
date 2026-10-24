#pragma once
#include <cstdint>
#include <map>
#include <vector>
#include <unordered_map>
#include <matcha/order.hpp>
#include <matcha/arena.hpp>
#include <matcha/price_level.hpp>

enum class Status {
    Ok,
    DuplicateId,  // an order with this id is already resting
    ArenaFull,    // no room to rest the order; it made no trades
    UnknownId     // cancel target is not resting in the book
};

class OrderBook {
    std::map<uint64_t, PriceLevel> bids;
    std::map<uint64_t, PriceLevel> asks;
    std::unordered_map<uint64_t, Order*> order_lookup;
    Arena arena;
    std::vector<uint64_t> filled_scratch;
    std::vector<uint64_t> empty_levels_scratch;
    void drain_filled_orders();
    void match_order(Order *order, std::vector<Trade> &trades);
    public:
    OrderBook(size_t n) : arena(n) {}
    bool contains_order(uint64_t order_id) const;
    const Order* get_order(uint64_t id) const;
    [[nodiscard]] Status insert_order(const Order &order, std::vector<Trade> &trades);
    [[nodiscard]] Status cancel_order(uint64_t order_id);
    void display_book();
};
