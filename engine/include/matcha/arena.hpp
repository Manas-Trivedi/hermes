#pragma once

#include <vector>
#include <cstdint>
#include <matcha/order.hpp>

class Arena {
private:
    std::vector<size_t> free_slots;
    std::vector<Order> storage;
    size_t next_free;
    size_t index_of(const Order *order) const;
public:
    explicit Arena(size_t);
    Order* allocate();
    void deallocate(Order *);
    bool full() const;
};
