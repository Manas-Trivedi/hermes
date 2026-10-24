#include <gtest/gtest.h>
#include <matcha/order_book.hpp>

TEST(OrderBookTest, LimitOrderRests) {
    OrderBook book(10);

    Order order;
    order.id = 1;
    order.side = Side::BUY;
    order.order_type = OrderType::LIMIT;
    order.price = 100;
    order.qty = 5;

    book.insert_order(order);
    EXPECT_TRUE(book.contains_order(1));
}

TEST(OrderBookTest, MarketOrderNeverRests) {
    OrderBook book(10);

    Order order;
    order.id = 1;
    order.side = Side::BUY;
    order.order_type = OrderType::MARKET;
    order.qty = 5;

    book.insert_order(order);
    EXPECT_FALSE(book.contains_order(1));
}

TEST(OrderBookTest, ComplteMatchingTest) {
    OrderBook book(10);

    Order sell_order;
    sell_order.id = 1;
    sell_order.side = Side::SELL;
    sell_order.order_type = OrderType::LIMIT;
    sell_order.price = 100;
    sell_order.qty = 5;

    Order buy_order;
    buy_order.id = 2;
    buy_order.side = Side::BUY;
    buy_order.order_type = OrderType::LIMIT;
    buy_order.price = 101;
    buy_order.qty = 5;

    book.insert_order(sell_order);

    EXPECT_TRUE(book.contains_order(1));

    book.insert_order(buy_order);

    EXPECT_FALSE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(2));
}

TEST(OrderBookTest, PartialMatchingTest) {
    OrderBook book(10);

    Order sell_order;
    sell_order.id = 1;
    sell_order.side = Side::SELL;
    sell_order.order_type = OrderType::LIMIT;
    sell_order.price = 100;
    sell_order.qty = 10;

    Order buy_order;
    buy_order.id = 2;
    buy_order.side = Side::BUY;
    buy_order.order_type = OrderType::LIMIT;
    buy_order.price = 101;
    buy_order.qty = 5;

    book.insert_order(sell_order);

    EXPECT_TRUE(book.contains_order(1));

    book.insert_order(buy_order);

    int remaining_qty = book.get_order(1)->qty;
    EXPECT_EQ(remaining_qty, 5);
    EXPECT_FALSE(book.contains_order(2));
}
