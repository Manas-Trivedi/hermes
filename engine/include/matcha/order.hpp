#pragma once
#include <cstdint>

enum class Side {
    BUY,
    SELL
};

enum class OrderType {
    LIMIT,
    MARKET,
    CANCEL
};

struct Trade {
    uint64_t taker_id; // incoming order
    uint64_t maker_id; // resting order it matched
    uint64_t price;    // the resting order's price
    uint64_t qty;
};

struct Order{
    uint64_t id;
    Side side;
    OrderType order_type;
    uint64_t price; // integer tics
    uint64_t qty; // current remaining qty
    Order *prev;
    Order *next;

    Order()
        : id(0),
          side(Side::BUY),
          order_type(OrderType::LIMIT),
          price(0),
          qty(0),
          prev(nullptr),
          next(nullptr)
    {}
};
