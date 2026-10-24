#include <cstdint>
#include <cassert>
#include <vector>
#include <stack>
#include <matcha/order.hpp>
#include <matcha/arena.hpp>

Arena::Arena(size_t capacity)
    :   storage(capacity),
        next_free(0)
{
    assert(capacity > 0);
}

size_t Arena::index_of(Order *order) {
    assert(order >= storage.data());
    assert(order < storage.data() + storage.size());
    return order - storage.data();
}

Order* Arena::allocate() {
    if(!free_slots.empty()) {
        size_t idx = free_slots.top();
        free_slots.pop();
        return &storage[idx];
    }
    if(full()) return nullptr;
    return &storage[next_free++];
}

void Arena::deallocate(Order *order) {
    size_t idx = index_of(order);
    free_slots.push(idx);
}

bool Arena::full() const {
    return free_slots.empty() && next_free >= storage.size();
}
