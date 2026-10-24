#include <cstdint>
#include <vector>
#include <map>
#include <iostream>
#include <matcha/order.hpp>
#include <matcha/price_level.hpp>
#include <matcha/order_book.hpp>

bool OrderBook::contains_order(uint64_t id) const {
    return order_lookup.count(id) > 0;
}

const Order* OrderBook::get_order(uint64_t id) const {
    auto it = order_lookup.find(id);
    if(it != order_lookup.end()) {
        return it->second;
    }
    return nullptr;
}

void OrderBook::drain_filled_orders() {
    for(uint64_t id : filled_scratch) {
        auto it = order_lookup.find(id);
        arena.deallocate(it->second);
        order_lookup.erase(it);
    }
    filled_scratch.clear();
}

Status OrderBook::cancel_order(uint64_t order_id) {
    auto found = order_lookup.find(order_id);
    if(found == order_lookup.end()) return Status::UnknownId;
    Order *order = found->second;
    if(order->side == Side::BUY) {
        auto level = bids.find(order->price);
        level->second.remove_order(order);
        if(level->second.empty()) bids.erase(level);
    } else {
        auto level = asks.find(order->price);
        level->second.remove_order(order);
        if(level->second.empty()) asks.erase(level);
    }
    order_lookup.erase(found);
    arena.deallocate(order);
    return Status::Ok;
}

void OrderBook::match_order(Order *order, std::vector<Trade> &trades) {
    uint64_t price = order->price;
    if(order->order_type == OrderType::MARKET) {
        price = (order->side == Side::BUY) ? UINT64_MAX : 0;
    }
    if(order->side == Side::BUY) {
        auto it = asks.begin();
        while(it != asks.end() && it->first <= price && order->qty > 0) {
            it->second.fill_order(order, trades, filled_scratch);
            drain_filled_orders();
            if(it->second.empty()) empty_levels_scratch.push_back(it->first);
            it++;
        }
        for(uint64_t key : empty_levels_scratch) asks.erase(key);
    } else {
        auto it = bids.rbegin();
        while(it != bids.rend() && it->first >= price && order->qty > 0) {
            it->second.fill_order(order, trades, filled_scratch);
            drain_filled_orders();
            if(it->second.empty()) empty_levels_scratch.push_back(it->first);
            it++;
        }
        for(uint64_t key : empty_levels_scratch) bids.erase(key);
    }
    empty_levels_scratch.clear();
}

Status OrderBook::insert_order(const Order &order, std::vector<Trade> &trades) {
    if(order.order_type == OrderType::CANCEL) return cancel_order(order.id);
    if(contains_order(order.id)) return Status::DuplicateId;

    // Match a copy so the caller's order is left untouched; the caller can
    // work out what remains from the trades.
    Order incoming = order;
    match_order(&incoming, trades);
    if(incoming.qty == 0 || incoming.order_type == OrderType::MARKET) return Status::Ok;

    // Capacity is checked after matching on purpose: if the order traded, the
    // makers it filled freed their slots, so the remainder always has room.
    Order *stored = arena.allocate();
    if(!stored) return Status::ArenaFull;
    *stored = incoming;
    order_lookup.emplace(stored->id, stored);
    auto &side = stored->side == Side::BUY ? bids : asks;
    side.try_emplace(stored->price, stored->price).first->second.add_order(stored);
    return Status::Ok;
}

void OrderBook::display_book() const {
     std::cout << " [ price ]  -> ";
        std::cout << "( qty, id )";
    std::cout << "\n";
    std::cout << "BIDS::\n";
    for(const auto &it: bids) {
        it.second.display_level();
    }
    std::cout << "ASKS::\n";
    for(const auto &it: asks) {
        it.second.display_level();
    }
}
