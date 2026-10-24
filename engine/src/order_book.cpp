#include <cstdint>
#include <stack>
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

void OrderBook::drain_filled_orders(std::queue<uint64_t> &matched_orders) {
    while(!matched_orders.empty()) {
        uint64_t id = matched_orders.front();
        arena.deallocate(order_lookup.at(id));
        order_lookup.erase(id);
        matched_orders.pop();
    }
}

void OrderBook::cancel_order(uint64_t order_id) {
    if(!order_lookup.count(order_id)) return;
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
}

void OrderBook::match_order(Order *order) {
    std::stack<uint64_t> emptyLevels;
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
            std::queue<uint64_t> matched_orders = it->second.fill_order(order);
            drain_filled_orders(matched_orders);
            if(it->second.empty()) emptyLevels.push(it->first);
            it++;
        }
        while(!emptyLevels.empty()) {
            uint64_t key = emptyLevels.top();
            asks.erase(key);
            emptyLevels.pop();
        }
    } else {
        auto it = bids.rbegin();
        while(it != bids.rend() && it->first >= price && order->qty > 0) {
            std::queue<uint64_t> matched_orders = it->second.fill_order(order);
            drain_filled_orders(matched_orders);
            if(it->second.empty()) emptyLevels.push(it->first);
            it++;
        }
        while(!emptyLevels.empty()) {
            uint64_t key = emptyLevels.top();
            bids.erase(key);
            emptyLevels.pop();
        }
    }
}

void OrderBook::insert_order(Order &order) {
    if(order.order_type == OrderType::CANCEL) return cancel_order(order.id);
    match_order(&order);
    if(order.qty == 0 || order.order_type == OrderType::MARKET) return;

    Order *stored = arena.allocate();
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
