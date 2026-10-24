#include <cstdint>
#include <vector>
#include <iostream>
#include <matcha/order.hpp>
#include <matcha/price_level.hpp>

bool PriceLevel::empty() const {
    return head == nullptr;
}

void PriceLevel::fill_order(Order *order, std::vector<Trade> &trades, std::vector<uint64_t> &filled) {
    Order *tmp = head;
    while(tmp && order->qty > 0) {
        uint64_t filledQty = std::min(order->qty, tmp->qty);
        order->qty -= filledQty;
        tmp->qty -= filledQty;
        trades.push_back({order->id, tmp->id, price, filledQty});
        if(tmp->qty == 0) {
            Order *delOrder = tmp;
            tmp = tmp->next;
            filled.push_back(delOrder->id);
            remove_order(delOrder);
            continue;
        }
        tmp = tmp->next;
    }
}

void PriceLevel::add_order(Order *order) {
    order->prev = nullptr;
    order->next = nullptr;
    if(head == nullptr) {
        head = order;
        tail = order;
    } else {
        order->prev = tail;
        tail->next = order;
        tail = order;
    }
}

void PriceLevel::remove_order(Order *order) {
    if(order == head && order == tail) {
        head = nullptr;
        tail = nullptr;
    } else if(head == order) {
        head = order->next;
        head->prev = nullptr;
    } else if(tail == order) {
        tail = order->prev;
        tail->next = nullptr;
    } else {
        order->prev->next = order->next;
        order->next->prev = order->prev;
    }
    order->next = nullptr;
    order->prev = nullptr;
}

void PriceLevel::display_level() const {
    std::cout << " [ " << price << " ]  -> ";
    const Order *tmp = head;
    while(tmp) {
        std::cout << "( " << tmp->qty << ", " << tmp->id << " )";
        if(tmp->next) std::cout << ", ";
        tmp = tmp->next;
    }
    std::cout << "\n";
}

void PriceLevel::snapshot(Side side, std::vector<BookEntry> &out) const {
    for(const Order *o = head; o; o = o->next) {
        out.push_back({side, o->id, price, o->qty});
    }
}
