#include <cstdint>
#include <stack>
#include <queue>
#include <vector>
#include <iostream>
#include <matcha/order.hpp>
#include <matcha/price_level.hpp>

bool PriceLevel::empty() {
    return head == nullptr;
}

std::queue<uint64_t> PriceLevel::fill_order(Order *order) {
    std::queue<uint64_t> matched_orders;
    Order *tmp = head;
    while(tmp && order->qty > 0) {
        uint64_t filledQty = std::min(order->qty, tmp->qty);
        order->qty -= filledQty;
        tmp->qty -= filledQty;
        if(tmp->qty == 0) {
            Order *delOrder = tmp;
            tmp = tmp->next;
            matched_orders.push(delOrder->id);
            remove_order(delOrder);
            continue;
        }
        tmp = tmp->next;
    }
    return matched_orders;
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

void PriceLevel::display_level() {
    std::cout << " [ " << price << " ]  -> ";
    Order *tmp = head;
    while(tmp) {
        std::cout << "( " << tmp->qty << ", " << tmp->id << " )";
        if(tmp->next) std::cout << ", ";
        tmp = tmp->next;
    }
    std::cout << "\n";
}
