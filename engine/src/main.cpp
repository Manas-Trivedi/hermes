#include <cstdint>
#include <vector>
#include <iostream>
#include <matcha/order.hpp>
#include <matcha/price_level.hpp>
#include <matcha/order_book.hpp>

void take_order(Order &order) {
    std::cout << "Enter order id::";
    std::cin >> order.id;
    uint64_t order_type;
    std::cout << "Enter order type(0/1/2)::";
    std::cin >> order_type;
    order.order_type = (order_type == 0) ? OrderType::LIMIT : (order_type == 1 ? OrderType::MARKET : OrderType::CANCEL);
    if(order_type != 2) {
        std::cout << "Enter order side(0/1)::";
        uint64_t side;
        std::cin >> side;
        order.side = (side == 0) ? Side::BUY : Side::SELL;
        if(order_type != 1) {
            std::cout << "Enter order price::";
            std::cin >> order.price;
        }
        std::cout << "Enter order quantity::";
        std::cin >> order.qty;
    }
}

int main() {
    size_t orders;
    std::cout << "Enter arena size: ";
    std::cin >> orders;
    std::cout << "Enter number of orders: ";
    size_t n;
    std::cin >> n;
    OrderBook book(orders);
    std::vector<Trade> trades;
    for(size_t i = 0; i < n; i++) {
        Order order;
        take_order(order);
        trades.clear();
        book.insert_order(order, trades);
        for(const Trade &t : trades) {
            std::cout << "TRADE taker=" << t.taker_id << " maker=" << t.maker_id
                      << " price=" << t.price << " qty=" << t.qty << "\n";
        }
    }
    book.display_book();
    return 0;
}
