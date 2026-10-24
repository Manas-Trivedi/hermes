#pragma once

#include <vector>
#include <stack>
#include <cstdint>
#include <matcha/order.hpp>

class Arena {
private:
    std::stack<size_t> free_slots;
    std::vector<Order> storage;
    size_t next_free;
    size_t index_of(Order *order);
public:
    Arena(size_t);
    Order* allocate();
    void deallocate(Order *);
    bool full() const;
};
