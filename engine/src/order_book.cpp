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
        arena.deallocate(order_lookup.at(id));
        order_lookup.erase(id);
    }
    filled_scratch.clear();
}

Status OrderBook::cancel_order(uint64_t order_id) {
    if(!order_lookup.count(order_id)) return Status::UnknownId;
    Order *order = order_lookup[order_id];
    Side side = order->side;
    uint64_t price = order->price;
    if(side == Side::BUY) {
        bids.at(price).remove_order(order);
        if(bids.at(price).empty()) bids.erase(price);
    } else {
        asks.at(price).remove_order(order);
        if(asks.at(price).empty()) asks.erase(price);
    }
    order_lookup.erase(order_id);
    arena.deallocate(order);
    return Status::Ok;
}

void OrderBook::match_order(Order *order, std::vector<Trade> &trades) {
    uint64_t price;
    if(order->order_type == OrderType::LIMIT) {
        price = order->price;
    }
    else if(order->order_type == OrderType::MARKET){
        if(order->side == Side::BUY) price = UINT64_MAX;
        else price = 0;
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

Status OrderBook::insert_order(Order &order, std::vector<Trade> &trades) {
    if(order.order_type == OrderType::CANCEL) return cancel_order(order.id);
    if(order_lookup.count(order.id)) return Status::DuplicateId;
    match_order(&order, trades);
    if(order.qty == 0 || order.order_type == OrderType::MARKET) return Status::Ok;

    // Capacity is checked after matching on purpose: if the order traded, the
    // makers it filled freed their slots, so the remainder always has room.
    Order *stored = arena.allocate();
    if(!stored) return Status::ArenaFull;
    *stored = order;
    order_lookup[stored->id] = stored;
    uint64_t price = stored->price;
    if(stored->side == Side::BUY) {
        if(!bids.count(price)) {
            bids.insert({price, PriceLevel(price)});
        }
        bids.at(price).add_order(stored);
    } else {
        if(!asks.count(price)) {
            asks.insert({price, PriceLevel(price)});
        }
        asks.at(price).add_order(stored);
    }
    return Status::Ok;
}

void OrderBook::display_book() {
     std::cout << " [ price ]  -> ";
        std::cout << "( qty, id )";
    std::cout << "\n";
    std::cout << "BIDS::\n";
    for(auto &it: bids) {
        it.second.display_level();
    }
    std::cout << "ASKS::\n";
    for(auto &it: asks) {
        it.second.display_level();
    }
}
